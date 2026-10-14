"""Triage one dispute: retrieve rules -> ask a model -> validate JSON -> apply review rule.

Usage (project root, venv active, LM Studio running for retrieval and Qwen):
    python src/triage.py --model claude --ids C001 C002     # specific cases
    python src/triage.py --model claude --n 10              # first 10 cases
    python src/triage.py --model claude --n 10 --out results/claude_smoke.jsonl
    python src/triage.py --model claude --ids C001 --show-prompt   # print the prompt, no API call
    python src/triage.py --model qwen-small --all --out results/qwen4b_v1.jsonl

Results are appended one JSON line per case. Cases already in --out are
skipped, so an interrupted run continues where it stopped. Run settings
(model, prompt version, LM Studio state, git commit) go to <out>.meta.jsonl.

Only merchant_type, amount, date and dispute_text are sent to the model. Gold
labels never go into the prompt.
"""

import argparse
import csv
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from llm import LLMError, call
from retrieve import general_rules, retrieve

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "data" / "cases_labelled.csv"

PROMPT_VERSION = "v2"  # default; choose with --prompt

CATEGORIES = [
    "fraud_unauthorised",
    "not_received",
    "not_as_described",
    "subscription_cancelled",
    "refund_not_processed",
    "processing_error",
    "unclear",
]

EVIDENCE_IDS = [
    "auth_3ds", "avs_cvv_match", "device_ip_history", "prior_undisputed_orders",
    "account_activity", "proof_of_delivery", "tracking_expected_date",
    "digital_access_logs", "service_provided_proof", "product_listing",
    "invoice_or_contract", "customer_communications", "replacement_offer",
    "return_cancellation_policy", "terms_acceptance", "subscription_terms",
    "cancellation_log", "post_cancellation_usage", "refund_issued_proof",
    "return_not_received", "transaction_records", "itemised_receipt",
    "currency_disclosure", "single_payment_proof", "authorisation_record",
    "timely_presentment_proof",
]

# Human-review rule from docs/prd.md. Starting values, to be tuned on results.
CONFIDENCE_THRESHOLD = 0.70
MIN_CONFIDENCE_GAP = 0.15
MIN_RETRIEVAL_SCORE = 0.50

# 0 = always pick the most likely next token (most repeatable). Applied to the
# local Qwen models. Claude can't be set (see llm.py) and runs at its default.
TEMPERATURE = 0


def effective_temperature(model_name):
    return "default (not settable)" if model_name == "claude" else TEMPERATURE

SYSTEM_PROMPT_V1 = f"""You help small UK merchants respond to card payment disputes (chargebacks).
You are given one dispute and some rule sections. Classify what the cardholder is claiming, recommend the evidence the merchant should submit, and explain briefly.

Categories (classify the cardholder's claim, not whether it is true):
- fraud_unauthorised: denies making or authorising the payment.
- not_received: paid, but goods, tickets or a booked service never arrived or never happened, including when the merchant moved or cancelled it and the customer didn't use the alternative.
- not_as_described: something was provided but was faulty, fake, wrong, incomplete, poor quality or different from what was promised.
- subscription_cancelled: a recurring payment taken after they cancelled or ended the agreement.
- refund_not_processed: they returned goods or cancelled a one-off order or booking, and an expected refund hasn't arrived.
- processing_error: charged twice, wrong amount, wrong currency, paid another way, declined but still charged, or charged very late.
- unclear: too vague to classify, or two categories fit equally well.

Evidence: choose 2 to 4 of these IDs, most important first. Use only these exact IDs:
{", ".join(EVIDENCE_IDS)}

Confidence: your probability (0 to 1) that the category is correct. Be honest: use below 0.7 when the complaint could reasonably fit another category.

Explanation: at most 3 short plain-English sentences (under 60 words) for the merchant. Cite the rule sections you relied on by ID in square brackets, e.g. [R2].

Reply with ONLY a JSON object, no other text, in exactly this shape:
{{"category": "<one category>", "confidence": <number>, "second_category": "<next most likely category>", "second_confidence": <number>, "required_evidence": ["<id>", "..."], "explanation": "<text>"}}"""



# v2 (after the v1 failure analysis, docs/failure_analysis_v1.md):
# H1 claim-priority rule, H2 recurring-charge signal, the received-or-used
# test, calibration guidance for confidence, and short worked examples.
# The examples are invented and deliberately unlike the eval cases.
SYSTEM_PROMPT_V2 = SYSTEM_PROMPT_V1.replace(
    "Evidence: choose 2 to 4",
    """Deciding between categories:
- Received or used? If the customer never received or used what they paid for, it's not_received. If they received or used it and it was poor or different, it's not_as_described.
- Two claims in one complaint? Classify the claim the merchant must act on first: (1) a refund or credit the merchant promised or confirmed that hasn't arrived: refund_not_processed; (2) a recurring or automatic repeat charge after the customer cancelled or gave notice: subscription_cancelled; (3) otherwise, the complaint about the goods or service itself.
- A second automatic charge for a pack, plan or membership after the customer gave notice counts as a recurring charge.

Worked examples (category, confidence):
- "The lamp arrived cracked. They said they'd refund £20 a month ago but nothing has come through." -> refund_not_processed 0.75 (two claims; the promised refund comes first)
- "I cancelled my meal-kit plan in March but they sent and charged April's box anyway." -> subscription_cancelled 0.9
- "Ordered size 9 trainers, received size 7." -> not_as_described 0.95

Evidence: choose 2 to 4""",
).replace(
    "Confidence: your probability (0 to 1) that the category is correct. Be honest: use below 0.7 when the complaint could reasonably fit another category.",
    "Confidence: your probability (0 to 1) that the category is correct. Use 0.9 or above only when one category clearly fits and no other is plausible. Use 0.6 to 0.8 when you applied the two-claims rule or a second category is reasonable. Use below 0.6 when the complaint is vague.",
)
assert SYSTEM_PROMPT_V2 != SYSTEM_PROMPT_V1

PROMPTS = {"v1": SYSTEM_PROMPT_V1, "v2": SYSTEM_PROMPT_V2}
SYSTEM_PROMPT = PROMPTS[PROMPT_VERSION]


def build_prompt(case, sections):
    rules = "\n\n".join(s["text"] for s in sections)
    return (
        f"GENERAL RULES\n{general_rules()}\n\n"
        f"RELEVANT RULE SECTIONS\n{rules}\n\n"
        f"DISPUTE\n"
        f"Merchant type: {case['merchant_type']}\n"
        f"Amount: £{case['amount_gbp']}\n"
        f"Transaction date: {case['transaction_date']}\n"
        f"Cardholder's complaint: {case['dispute_text']}\n\n"
        f"Reply with the JSON object only."
    )


def parse_reply(text):
    """Extract and validate the JSON object. Returns (data, errors)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None, ["no JSON object found"]
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        return None, [f"invalid JSON: {e.msg}"]

    errors = []
    if data.get("category") not in CATEGORIES:
        errors.append(f"category must be one of {CATEGORIES}")
    for key in ("confidence", "second_confidence"):
        v = data.get(key)
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            errors.append(f"{key} must be a number between 0 and 1")
    if data.get("second_category") not in CATEGORIES:
        errors.append("second_category must be one of the categories")
    if not isinstance(data.get("required_evidence"), list) or not data["required_evidence"]:
        errors.append("required_evidence must be a non-empty list")
    if not isinstance(data.get("explanation"), str) or not data["explanation"].strip():
        errors.append("explanation must be a non-empty string")
    return (data if not errors else None), errors


def review_reasons(data, sections):
    """Apply the PRD human-review rule. Returns a list of reasons (empty = no review)."""
    reasons = []
    if data is None:
        return ["invalid output after retry"]
    if data["category"] == "unclear":
        reasons.append("model said unclear")
    if data["confidence"] < CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence below {CONFIDENCE_THRESHOLD}")
    if data["confidence"] - data["second_confidence"] < MIN_CONFIDENCE_GAP:
        reasons.append(f"top two within {MIN_CONFIDENCE_GAP}")
    if not sections or sections[0]["score"] < MIN_RETRIEVAL_SCORE:
        reasons.append(f"no rule section scored above {MIN_RETRIEVAL_SCORE}")
    return reasons


def triage(case, model_name, k=3, max_tokens=1000):
    """Run the full pipeline on one case and return a flat result dict."""
    t0 = time.perf_counter()
    sections = retrieve(case["dispute_text"], k=k)
    retrieval_seconds = time.perf_counter() - t0

    prompt = build_prompt(case, sections)
    calls = [call(model_name, prompt, system=SYSTEM_PROMPT, max_tokens=max_tokens, temperature=TEMPERATURE)]
    data, errors = parse_reply(calls[0]["text"])
    if calls[0]["output_tokens"] is not None and calls[0]["output_tokens"] >= max_tokens:
        data, errors = None, ["reply was cut off because it was too long; keep the explanation under 60 words"]
    first_errors = errors
    if data is None:
        # One retry: show the model its reply and what was wrong with it.
        retry_prompt = (
            f"{prompt}\n\nYour previous reply was:\n{calls[0]['text']}\n\n"
            f"It was not valid because: {'; '.join(errors)}.\n"
            f"Reply again with ONLY the corrected JSON object."
        )
        calls.append(call(model_name, retry_prompt, system=SYSTEM_PROMPT, max_tokens=max_tokens, temperature=TEMPERATURE))
        data, errors = parse_reply(calls[1]["text"])
        if calls[1]["output_tokens"] is not None and calls[1]["output_tokens"] >= max_tokens:
            data, errors = None, ["reply was cut off again"]

    evidence, invalid, cited = [], [], []
    if data:
        evidence = [e for e in data["required_evidence"] if e in EVIDENCE_IDS]
        invalid = [e for e in data["required_evidence"] if e not in EVIDENCE_IDS]
        cited = sorted(set(re.findall(r"\bR\d\b", data["explanation"])))
    available = {"R0"} | {s["id"] for s in sections}
    reasons = review_reasons(data, sections)

    def total(key):
        vals = [c[key] for c in calls if c.get(key) is not None]
        return sum(vals) if vals else None

    return {
        "id": case["id"],
        "model": model_name,
        "model_id": calls[0]["model_id"],
        "prompt_version": PROMPT_VERSION,
        "temperature": effective_temperature(model_name),
        "category": data["category"] if data else None,
        "confidence": data["confidence"] if data else None,
        "second_category": data["second_category"] if data else None,
        "second_confidence": data["second_confidence"] if data else None,
        "required_evidence": evidence,
        "invalid_evidence": invalid,
        "explanation": data["explanation"] if data else None,
        "cited_sections": cited,
        "cited_not_provided": [c for c in cited if c not in available],
        "retrieved": [f"{s['id']}:{s['score']:.3f}" for s in sections],
        "needs_human_review": bool(reasons),
        "review_reasons": reasons,
        "valid_json": data is not None,
        "first_try_valid": not first_errors,
        "errors": errors,
        "first_try_errors": first_errors,
        "retrieval_seconds": round(retrieval_seconds, 3),
        "ttft_seconds": calls[0]["ttft_seconds"],
        "llm_seconds": total("total_seconds"),
        "total_seconds": round(retrieval_seconds + (total("total_seconds") or 0), 3),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "tokens_per_second": calls[-1]["tokens_per_second"],
        "raw_reply": calls[-1]["text"],
        "first_raw_reply": calls[0]["text"] if len(calls) > 1 else None,
    }


def load_cases():
    with CASES_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_metadata(args, model_name):
    """Everything needed to reproduce a run, saved next to the results file."""
    meta = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "model": model_name,
        "model_id": os.getenv({"qwen-small": "QWEN_SMALL", "qwen-large": "QWEN_LARGE", "claude": "CLAUDE_MODEL"}[model_name]),
        "embed_model": os.getenv("EMBED_MODEL"),
        "prompt_version": PROMPT_VERSION,
        "k": args.k,
        "max_tokens": 1000,
        "temperature": effective_temperature(model_name),
        "thinking": False,
        "review_rule": {"confidence": CONFIDENCE_THRESHOLD, "gap": MIN_CONFIDENCE_GAP, "retrieval": MIN_RETRIEVAL_SCORE},
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    for key, cmd in (("git_commit", ["git", "rev-parse", "--short", "HEAD"]),
                     ("lms_loaded_models", ["lms", "ps"]),
                     ("lms_version", ["lms", "version"])):
        try:
            meta[key] = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=ROOT).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            meta[key] = "unavailable"
    return meta


def main():
    global PROMPT_VERSION, SYSTEM_PROMPT
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, choices=["qwen-small", "qwen-large", "claude"])
    parser.add_argument("--ids", nargs="+", help="case ids, e.g. C001 C002")
    parser.add_argument("--n", type=int, help="run the first N cases")
    parser.add_argument("--all", action="store_true", help="run every case")
    parser.add_argument("-k", type=int, default=3, help="rule sections to retrieve (default 3)")
    parser.add_argument("--out", help="append results to this .jsonl file")
    parser.add_argument("--redo", action="store_true", help="rerun cases already in --out (default: skip them)")
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default=PROMPT_VERSION, help="prompt version (default %(default)s)")
    parser.add_argument("--show-prompt", action="store_true", help="print the prompt and stop (no model call)")
    args = parser.parse_args()

    PROMPT_VERSION, SYSTEM_PROMPT = args.prompt, PROMPTS[args.prompt]

    cases = load_cases()
    if args.ids:
        wanted = set(args.ids)
        cases = [c for c in cases if c["id"] in wanted]
    elif args.n:
        cases = cases[: args.n]
    elif not args.all:
        parser.error("give --ids, --n or --all")

    try:
        if args.show_prompt:
            c = cases[0]
            print("=== SYSTEM ===\n" + SYSTEM_PROMPT + "\n\n=== USER ===\n" + build_prompt(c, retrieve(c["dispute_text"], k=args.k)))
            return

        out = None
        if args.out:
            out_path = Path(args.out)
            done = set()
            if out_path.exists() and not args.redo:
                done = {json.loads(l)["id"] for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()}
                skipped = [c["id"] for c in cases if c["id"] in done]
                cases = [c for c in cases if c["id"] not in done]
                if skipped:
                    print(f"Skipping {len(skipped)} cases already in {args.out} (use --redo to rerun them)")
            meta_path = out_path.with_suffix(".meta.jsonl")
            with meta_path.open("a", encoding="utf-8") as m:
                m.write(json.dumps(run_metadata(args, args.model)) + "\n")
            print(f"Run settings saved to {meta_path}")
            out = out_path.open("a", encoding="utf-8")

        correct = 0
        for c in cases:
            r = triage(c, args.model, k=args.k)
            r["timestamp"] = datetime.now().isoformat(timespec="seconds")
            ok = r["category"] == c["true_category"]
            correct += ok
            flag = "REVIEW" if r["needs_human_review"] else ""
            conf = f"{r['confidence']:.2f}" if r["confidence"] is not None else "  - "
            tps = f"{r['tokens_per_second']:.0f} tok/s" if r["tokens_per_second"] else ""
            ttft = f"ttft {r['ttft_seconds']:.2f}s" if r["ttft_seconds"] is not None else ""
            print(f"{r['id']}  {'✓' if ok else '✗'}  {str(r['category']):24} {conf}  gold={c['true_category']:24} "
                  f"json={'ok' if r['first_try_valid'] else ('retry-ok' if r['valid_json'] else 'FAIL')}  "
                  f"{r['total_seconds']:.1f}s  {ttft}  {tps}  {flag}")
            if r["invalid_evidence"]:
                print(f"       invalid evidence ids: {r['invalid_evidence']}")
            if out:
                out.write(json.dumps(r) + "\n")
                out.flush()
        if cases:
            print(f"\nCategory correct: {correct}/{len(cases)} (raw; run score.py for the full report)")
        if out:
            out.close()
            print(f"Saved to {args.out}")
    except LLMError as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\nStopped. Finished cases are saved; rerun the same command to continue where you left off.")


if __name__ == "__main__":
    main()
