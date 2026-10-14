"""Retrieve the most relevant dispute rule sections for a case (the "R" in RAG).

How it works:
1. Split rules/dispute_rules.md into chunks, one per "## " section (R0-R7).
2. Turn each chunk into an embedding (a list of numbers that captures its
   meaning) using the local nomic-embed-text model in LM Studio.
3. Save the embeddings to rules/rules_index.json so they're only computed once.
4. For a new case, embed its text and return the k chunks whose embeddings are
   most similar (cosine similarity). R0 (general rules) is never ranked; use
   general_rules() to always include it in the prompt instead.

Usage (from the project root, with the venv active and LM Studio running):
    python src/retrieve.py "my parcel never arrived"   # show the top 3 sections
    python src/retrieve.py --build                     # force a rebuild of the index
    python src/retrieve.py --check                     # retrieval hit rate on the eval set
"""

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

from llm import LLMError, _openai_client, _require_env

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "rules" / "dispute_rules.md"
INDEX_PATH = ROOT / "rules" / "rules_index.json"
CASES_PATH = ROOT / "data" / "cases_labelled.csv"

# nomic-embed-text was trained with these prefixes. Documents and questions
# get different ones, and leaving them out noticeably worsens retrieval.
# Sections that are always given to the model rather than competing in retrieval.
ALWAYS_INCLUDE = {"R0"}

DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def load_chunks():
    """Split the rules file into one chunk per '## ' section.

    Returns a list of dicts: {"id": "R2", "title": "...", "text": "..."}.
    The intro above the first '## ' heading is skipped.
    """
    chunks = []
    current = None
    for line in RULES_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current:
                chunks.append(current)
            title = line[3:].strip()
            chunk_id = title.split(" ", 1)[0]  # "R2 · not_received: ..." -> "R2"
            current = {"id": chunk_id, "title": title, "lines": [line]}
        elif current:
            current["lines"].append(line)
    if current:
        chunks.append(current)
    for c in chunks:
        c["text"] = "\n".join(c.pop("lines")).strip()
    return chunks


def embed(texts):
    """Embed a list of strings with the model named EMBED_MODEL in .env."""
    model = _require_env("EMBED_MODEL")
    try:
        response = _openai_client().embeddings.create(model=model, input=texts)
    except Exception as e:  # connection and HTTP errors from LM Studio
        raise LLMError(
            f"Embedding failed with model '{model}'. Is LM Studio running with the "
            f"embedding model loaded? ({e})"
        ) from e
    return [item.embedding for item in response.data]


def _fingerprint():
    """A short hash of the rules text plus the model name.

    Used to rebuild the index automatically whenever either changes.
    """
    h = hashlib.sha256()
    h.update(RULES_PATH.read_bytes())
    h.update(_require_env("EMBED_MODEL").encode())
    return h.hexdigest()[:16]


def build_index():
    chunks = load_chunks()
    vectors = embed([DOC_PREFIX + c["text"] for c in chunks])
    index = {
        "fingerprint": _fingerprint(),
        "model": _require_env("EMBED_MODEL"),
        "chunks": [dict(c, vector=v) for c, v in zip(chunks, vectors)],
    }
    INDEX_PATH.write_text(json.dumps(index), encoding="utf-8")
    print(f"Built index: {len(chunks)} sections -> {INDEX_PATH.name}", file=sys.stderr)
    return index


_index_cache = None


def load_index():
    """Load the saved index, rebuilding it if the rules or model have changed."""
    global _index_cache
    if _index_cache is None:
        if INDEX_PATH.exists():
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if index.get("fingerprint") != _fingerprint():
                index = build_index()
        else:
            index = build_index()
        _index_cache = index
    return _index_cache


def cosine(a, b):
    """Similarity between two embeddings: 1 = same meaning, 0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def retrieve(text, k=3):
    """Return the k rule sections most similar to text, best first.

    Each result is {"id", "title", "text", "score"}.
    """
    index = load_index()
    query_vector = embed([QUERY_PREFIX + text])[0]
    scored = [
        {"id": c["id"], "title": c["title"], "text": c["text"], "score": cosine(query_vector, c["vector"])}
        for c in index["chunks"]
        if c["id"] not in ALWAYS_INCLUDE
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]


def general_rules():
    """The always-included sections (R0), as one string for the prompt."""
    return "\n\n".join(c["text"] for c in load_index()["chunks"] if c["id"] in ALWAYS_INCLUDE)


def check(k=3):
    """For each labelled case, is the rule section for its gold category in the top k?

    This measures retrieval on its own, before any LLM is involved.
    """
    index = load_index()
    section_for = {}
    for c in index["chunks"]:
        # "R2 · not_received: ..." -> category "not_received"
        rest = c["title"].split("·", 1)[-1].strip()
        section_for[rest.split(":", 1)[0].strip()] = c["id"]

    with CASES_PATH.open(newline="", encoding="utf-8") as f:
        cases = [r for r in csv.DictReader(f) if r["true_category"] != "unclear"]

    # Batches 1-2 are the "dev" half used to look at misses and improve the
    # rules; batches 3-4 are "held out". If held-out scores rise as much as dev
    # scores, the improvement is general rather than tuned to specific cases.
    stats = {"dev (batches 1-2)": [0, 0, 0], "held out (batches 3-4)": [0, 0, 0]}
    misses = []
    for case in cases:
        half = "dev (batches 1-2)" if case["batch"] in ("1", "2") else "held out (batches 3-4)"
        want = section_for[case["true_category"]]
        got = [r["id"] for r in retrieve(case["dispute_text"], k=k)]
        s = stats[half]
        s[0] += 1
        s[1] += got[0] == want
        s[2] += want in got
        if want not in got:
            misses.append((case["id"], case["true_category"], want, got))

    n = len(cases)
    top1 = sum(s[1] for s in stats.values())
    topk = sum(s[2] for s in stats.values())
    print(f"Cases checked: {n}")
    print(f"Correct section ranked 1st:   {top1}/{n} ({top1 / n:.0%})")
    print(f"Correct section in top {k}:    {topk}/{n} ({topk / n:.0%})")
    for half, (m, t1, tk) in stats.items():
        print(f"  {half}: 1st {t1}/{m} ({t1 / m:.0%}), top {k} {tk}/{m} ({tk / m:.0%})")
    if misses:
        print(f"\nMisses (case, gold category, wanted, got):")
        for m in misses:
            print("  ", *m)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="dispute text to look up")
    parser.add_argument("-k", type=int, default=3, help="number of sections to return (default 3)")
    parser.add_argument("--build", action="store_true", help="rebuild the index now")
    parser.add_argument("--check", action="store_true", help="measure retrieval against the eval set")
    args = parser.parse_args()

    try:
        if args.build:
            build_index()
        if args.check:
            check(args.k)
        elif args.text:
            for r in retrieve(args.text, k=args.k):
                print(f"{r['score']:.3f}  {r['title']}")
        elif not args.build:
            parser.print_help()
    except LLMError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
