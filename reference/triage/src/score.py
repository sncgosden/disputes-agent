"""Score a results file against the gold labels. The same code grades every model.

Usage:
    python src/score.py results/claude_smoke2.jsonl
    python src/score.py results/claude_v1.jsonl --md results/claude_v1_score.md --csv results/claude_v1.csv
    python src/score.py results/claude_v1.jsonl --price-in 3 --price-out 15   # USD per million tokens

If a case appears more than once in the file (e.g. after a rerun), the last
result is used. Only cases present in the file are scored.

Definitions (from docs/prd.md):
- Accuracy: predicted category == gold, on cases the system did NOT mark
  `unclear`. Raw accuracy (all cases, unclear or invalid counted wrong) is
  also shown.
- Evidence recall: share of the gold evidence IDs the model named, averaged
  over cases (invalid outputs count as 0).
- Review rate: share of cases flagged for human review.
- Confident-but-wrong rate: share of cases NOT flagged for review that are
  wrong. These are the dangerous errors, because no human sees them.
"""

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "data" / "cases_labelled.csv"

LOCAL_MODELS = {"qwen-small", "qwen-large"}
CONF_BUCKETS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.01)]


def load(results_path):
    with CASES_PATH.open(newline="", encoding="utf-8") as f:
        gold = {r["id"]: r for r in csv.DictReader(f)}
    results = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            results[r["id"]] = r  # last one wins
    return gold, results


def pct(a, b):
    return f"{a}/{b} ({a / b:.0%})" if b else "n/a"


def p90(values):
    v = sorted(values)
    return v[max(0, int(round(0.9 * len(v))) - 1)] if v else None


def review_flags(r, threshold, gap, min_retrieval):
    """Recompute the review rule with different settings (for the threshold sweep)."""
    if not r["valid_json"]:
        return True
    top_score = float(r["retrieved"][0].split(":")[1]) if r["retrieved"] else 0
    return (
        r["category"] == "unclear"
        or r["confidence"] < threshold
        or r["confidence"] - r["second_confidence"] < gap
        or top_score < min_retrieval
    )


def score(results_path, price_in=None, price_out=None):
    gold, results = load(results_path)
    rows = []
    for cid, r in results.items():
        g = gold[cid]
        gold_ev = [e for e in g["required_evidence"].split(";") if e]
        pred_ev = r["required_evidence"] if r["valid_json"] else []
        hit = len(set(gold_ev) & set(pred_ev))
        rows.append({
            "id": cid,
            "difficulty": g["difficulty"],
            "gold": g["true_category"],
            "pred": r["category"],
            "correct": r["category"] == g["true_category"],
            "said_unclear": r["category"] == "unclear",
            "valid": r["valid_json"],
            "first_try_valid": r["first_try_valid"],
            "confidence": r["confidence"],
            "review": r["needs_human_review"],
            "review_reasons": "; ".join(r["review_reasons"]),
            "evidence_recall": hit / len(gold_ev) if gold_ev else 1.0,
            "evidence_precision": hit / len(pred_ev) if pred_ev else 0.0,
            "gold_evidence": ";".join(gold_ev),
            "pred_evidence": ";".join(pred_ev),
            "invalid_evidence": ";".join(r.get("invalid_evidence", [])),
            "cited_not_provided": ";".join(r.get("cited_not_provided", [])),
            "total_seconds": r["total_seconds"],
            "ttft_seconds": r["ttft_seconds"],
            "input_tokens": r.get("input_tokens"),
            "output_tokens": r.get("output_tokens"),
            "explanation": r.get("explanation"),
            "_raw": r,
        })
    rows.sort(key=lambda x: x["id"])
    model = next(iter(results.values()))["model"]
    model_id = next(iter(results.values()))["model_id"]
    n = len(rows)
    out = []
    w = out.append

    w(f"# Scores: {Path(results_path).name}")
    w(f"Model: `{model}` ({model_id}) · prompt {next(iter(results.values())).get('prompt_version', '?')} · {n} cases\n")

    # --- Quality ---
    decided = [x for x in rows if x["valid"] and not x["said_unclear"]]
    auto = [x for x in rows if not x["review"]]
    w("## Quality")
    w("| Metric | Value | PRD target |")
    w("|---|---|---|")
    w(f"| Category accuracy (excl. `unclear`) | {pct(sum(x['correct'] for x in decided), len(decided))} | ≥ 85% |")
    w(f"| Raw accuracy (all cases) | {pct(sum(x['correct'] for x in rows), n)} | |")
    for d in ("easy", "ambiguous"):
        sub = [x for x in decided if x["difficulty"] == d]
        w(f"| Accuracy, {d} | {pct(sum(x['correct'] for x in sub), len(sub))} | |")
    rec = statistics.mean(x["evidence_recall"] for x in rows) if rows else 0
    prec = statistics.mean(x["evidence_precision"] for x in rows) if rows else 0
    w(f"| Evidence recall | {rec:.0%} | ≥ 80% |")
    w(f"| Evidence precision | {prec:.0%} | |")
    w(f"| Review rate | {pct(sum(x['review'] for x in rows), n)} | ≤ 30% |")
    w(f"| Confident-but-wrong rate | {pct(sum(not x['correct'] for x in auto), len(auto))} | ≤ 5% |")
    w(f"| Valid JSON (after retry) | {pct(sum(x['valid'] for x in rows), n)} | 100% |")
    w(f"| Valid JSON first try | {pct(sum(x['first_try_valid'] for x in rows), n)} | |")
    w(f"| Cases with made-up evidence IDs | {pct(sum(bool(x['invalid_evidence']) for x in rows), n)} | |")
    w(f"| Cases citing a section not provided | {pct(sum(bool(x['cited_not_provided']) for x in rows), n)} | |")
    w(f"| Model said `unclear` | {pct(sum(x['said_unclear'] for x in rows), n)} | |")
    w("")

    # --- Speed and cost ---
    tot = [x["total_seconds"] for x in rows if x["total_seconds"] is not None]
    ttft = [x["ttft_seconds"] for x in rows if x["ttft_seconds"] is not None]
    tin = [x["input_tokens"] for x in rows if x["input_tokens"] is not None]
    tout = [x["output_tokens"] for x in rows if x["output_tokens"] is not None]
    w("## Speed and cost")
    w("| Metric | Value |")
    w("|---|---|")
    if tot:
        w(f"| Latency median / p90 | {statistics.median(tot):.1f}s / {p90(tot):.1f}s |")
    if ttft:
        w(f"| Time to first token, median | {statistics.median(ttft):.2f}s |")
    if tin and tout:
        w(f"| Tokens per case, mean in / out | {statistics.mean(tin):.0f} / {statistics.mean(tout):.0f} |")
        if model in LOCAL_MODELS:
            w("| Cost per case | £0 marginal (local) |")
        elif price_in is not None and price_out is not None:
            per_case = (statistics.mean(tin) * price_in + statistics.mean(tout) * price_out) / 1_000_000
            w(f"| Cost per case / per 1,000 cases | ${per_case:.4f} / ${per_case * 1000:.2f} (at ${price_in}/${price_out} per M tokens) |")
        else:
            w("| Cost | add --price-in and --price-out (USD per million tokens) |")
    w("")

    # --- Per category ---
    w("## By gold category")
    w("| Category | Correct | Evidence recall |")
    w("|---|---|---|")
    by_cat = defaultdict(list)
    for x in rows:
        by_cat[x["gold"]].append(x)
    for cat, xs in sorted(by_cat.items()):
        w(f"| {cat} | {pct(sum(x['correct'] for x in xs), len(xs))} | {statistics.mean(x['evidence_recall'] for x in xs):.0%} |")
    w("")

    # --- Errors ---
    errs = Counter((x["gold"], x["pred"]) for x in rows if not x["correct"])
    if errs:
        w("## Errors (gold → predicted)")
        for (g, p), c in errs.most_common():
            ids = [x["id"] for x in rows if x["gold"] == g and x["pred"] == p]
            w(f"- {g} → {p}: {c}  ({', '.join(ids)})")
        w("")

    # --- Calibration ---
    w("## Calibration (does confidence match accuracy?)")
    w("| Confidence | Cases | Accuracy |")
    w("|---|---|---|")
    for lo, hi in CONF_BUCKETS:
        xs = [x for x in rows if x["confidence"] is not None and lo <= x["confidence"] < hi]
        label = f"{lo:.2f}–{min(hi, 1):.2f}"
        w(f"| {label} | {len(xs)} | {pct(sum(x['correct'] for x in xs), len(xs)) if xs else '–'} |")
    w("")

    # --- Threshold sweep ---
    w("## Review threshold sweep (gap 0.15, retrieval 0.50 held fixed)")
    w("| Confidence threshold | Review rate | Confident-but-wrong |")
    w("|---|---|---|")
    for t in (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95):
        flags = [review_flags(x["_raw"], t, 0.15, 0.50) for x in rows]
        auto_t = [x for x, f in zip(rows, flags) if not f]
        mark = " ← current" if t == 0.7 else ""
        w(f"| {t:.2f}{mark} | {pct(sum(flags), n)} | {pct(sum(not x['correct'] for x in auto_t), len(auto_t))} |")
    w("")
    return "\n".join(out), rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", help="a .jsonl file written by triage.py")
    parser.add_argument("--md", help="also save the report as markdown")
    parser.add_argument("--csv", help="also save one row per case (results + gold + scores)")
    parser.add_argument("--price-in", type=float, help="USD per million input tokens (Claude)")
    parser.add_argument("--price-out", type=float, help="USD per million output tokens (Claude)")
    args = parser.parse_args()

    if not Path(args.results).exists() or not Path(args.results).read_text(encoding="utf-8").strip():
        raise SystemExit(f"No results in {args.results}. Run triage.py with --out {args.results} first (or check it finished).")
    report, rows = score(args.results, args.price_in, args.price_out)
    print(report)
    if args.md:
        Path(args.md).write_text(report + "\n", encoding="utf-8")
        print(f"Saved report to {args.md}")
    if args.csv:
        fields = [k for k in rows[0] if not k.startswith("_")]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=fields)
            wr.writeheader()
            for x in rows:
                wr.writerow({k: x[k] for k in fields})
        print(f"Saved per-case rows to {args.csv}")


if __name__ == "__main__":
    main()
