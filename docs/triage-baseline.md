# Triage baseline

The case-preparation agent builds on an earlier dispute triage classifier. One run of that classifier is kept as a fixed reference point: what the earlier approach produced, and where it fell short.

## Run

5 October 2026, one synthetic case (C001), from the triage source at commit `f7db5279c8743abb7e1d667a187c22652932f256`:

```sh
./.venv/bin/python src/triage.py --model qwen-large --ids C001 --out /Users/sebastian/Developer/disputes-agent/baseline/qwen-step-1.jsonl
```

Model `qwen3.5-9b-mlx` through LM Studio's local server, with the nomic embedding model for rule retrieval; 19.2 seconds. The exact source files are kept in `baseline/source-v1/`, so the run does not depend on the original repository. The later triage code reused for comparison is in `reference/triage/` (commit `e6e8d9e29f18e7cb65908e4b8943ebd83b51f20f`).

| File | Contents |
|---|---|
| `baseline/C001-input.json` | The four merchant-visible complaint fields, without labels |
| `baseline/qwen-step-1.jsonl` | Result, raw model reply, retrieval and timing |
| `baseline/run-manifest.json` | Command, source commit, file hashes, configuration and checks |

Check the saved run against its manifest with `python3 scripts/verify_baseline.py`. Model output is not guaranteed to reproduce exactly; comparisons record model, prompt, runtime and input versions.

## Result

Category `subscription_cancelled`, matching the reviewed label. Valid JSON on the first attempt; all evidence IDs within the vocabulary (cancellation_log, post_cancellation_usage, subscription_terms, terms_acceptance). Retrieved rules R4 (0.734), R5 (0.651), R6 (0.637).

## Where it fell short

1. **No citation, and nothing noticed.** The reply cited no rule section, yet validation passed: it rejected unknown citations but not an empty list.
2. **It presumed a defence.** The complaint reports a confirmed cancellation and no later use. Those are the customer's claims, so the right output asks the merchant to check their records; instead the explanation told the merchant to prove the cancellation invalid.
3. **The review gate missed both.** `needs_human_review` was false because the gate relied on the model's own confidence and the retrieval score, which say nothing about either problem.

The pipeline ran; the advice was not reliable. The output is kept unchanged as a failure example.

## What the case-preparation agent does differently

- Prepares a case for a person to review rather than classifying a dispute or aiming to win it.
- Code, not the model, decides permissions and whether a draft is ready.
- Every claim must cite a record; a customer's statement is recorded as a claim, not a fact.
- Missing facts are asked for, not assumed.
