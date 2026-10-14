# Model comparison: v1 and v2

All runs scored on the same corrected labels (after the H1/H2 relabels of C016, C030, C065). v1 = original prompt; v2 = claim-priority rule, recurring signal, calibration guidance, worked examples. Claude was not rerun with v2.

Same 80 cases, retrieval and scorer for every run (the prompt version is in each run name). Claude priced at $2.0/$10.0 per M tokens.

## Quality, safety, speed and cost

| Metric | claude_v1 | qwen4b_v1 | qwen4b_v2 | qwen9b_v1 | qwen9b_v2 | Target |
|---|---|---|---|---|---|---|
| Model | `claude-sonnet-5-5` | `qwen3.5-4b` | `qwen3.5-4b` | `qwen3.5-9b-mlx` | `qwen3.5-9b-mlx` |  |
| Category accuracy | 98% ✓ | 95% ✓ | 96% ✓ | 96% ✓ | 89% ✓ | ≥ 85% |
| Accuracy, easy / ambiguous | 100% / 92% | 100% / 83% | 100% / 88% | 98% / 92% | 95% / 75% |  |
| Evidence recall | 83% ✓ | 75% ✗ | 69% ✗ | 70% ✗ | 66% ✗ | ≥ 80% |
| Evidence precision | 50% | 46% | 47% | 41% | 38% |  |
| Confident-but-wrong @ 0.7 | 0.0% ✓ | 5.1% ✗ | 3.8% ✓ | 3.8% ✓ | 9.2% ✗ | ≤ 5% |
| Review rate @ 0.7 | 14% ✓ | 2% ✓ | 0% ✓ | 1% ✓ | 5% ✓ | ≤ 30% |
| Safe threshold range | 0.50–0.87 | none ✗ | 0.50–0.90 | 0.50–0.95 | 0.86–0.95 | meets both |
| …review / confident-but-wrong at top of range | 30% / 0% | – | 12% / 4% | 19% / 2% | 25% / 2% |  |
| Valid JSON first try | 99% | 96% | 94% | 100% | 100% |  |
| Latency median / p90 | 2.5s / 6.3s | 4.5s / 7.1s | 5.3s / 8.2s | 11.7s / 17.4s | 9.3s / 13.2s |  |
| Cost per 1,000 cases | $8.57 | £0 (local) | £0 (local) | £0 (local) | £0 (local) |  |

*Safe threshold range* = every confidence threshold at which confident-but-wrong ≤ 5% AND review rate ≤ 30%. The top of the range is the safest setting that still respects the review cap. Confidence scales differ between models, so one shared threshold is not fair to all of them.

## Error overlap

- Wrong for **every** model (0): none. These are likely hard or debatable cases; recheck their labels.
- Wrong only for claude_v1 (0): none
- Wrong only for qwen4b_v1 (2): C065, C072
- Wrong only for qwen4b_v2 (0): none
- Wrong only for qwen9b_v1 (0): none
- Wrong only for qwen9b_v2 (4): C027, C046, C050, C053
- Wrong for at least one model: 12 of 80 cases

| Case | Gold | claude_v1 | qwen4b_v1 | qwen4b_v2 | qwen9b_v1 | qwen9b_v2 |
|---|---|---|---|---|---|---|
| C016 | not_as_described | refund_not_processed (0.55) | ✓ | ✓ | ✓ | refund_not_processed (0.85) |
| C027 | subscription_cancelled | ✓ | ✓ | ✓ | ✓ | refund_not_processed (0.75) |
| C044 | refund_not_processed | ✓ | not_as_described (0.92) | not_as_described (0.9) | ✓ | ✓ |
| C046 | not_received | ✓ | ✓ | ✓ | ✓ | refund_not_processed (0.85) |
| C047 | not_as_described | ✓ | ✓ | ✓ | refund_not_processed (0.85) | refund_not_processed (0.85) |
| C048 | refund_not_processed | ✓ | subscription_cancelled (0.92) | subscription_cancelled (0.95) | subscription_cancelled (0.95) | subscription_cancelled (0.95) |
| C050 | processing_error | ✓ | ✓ | ✓ | ✓ | refund_not_processed (0.85) |
| C053 | processing_error | ✓ | ✓ | ✓ | ✓ | subscription_cancelled (0.85) |
| C055 | processing_error | fraud_unauthorised (0.62) | fraud_unauthorised (0.92) | ✓ | ✓ | subscription_cancelled (0.85) |
| C056 | not_as_described | ✓ | ✓ | subscription_cancelled (0.9) | subscription_cancelled (0.85) | subscription_cancelled (0.85) |
| C065 | refund_not_processed | ✓ | not_as_described (0.92) | ✓ | ✓ | ✓ |
| C072 | refund_not_processed | ✓ | unclear (0.85) | ✓ | ✓ | ✓ |


## Routing (simulated from the saved runs above)

Local models: `qwen4b_v2` (small), `qwen9b_v1` (large). Escalation target: Claude (`claude_v1`). Claude priced at $2.0/$10.0 per M tokens. Local models are £0 marginal cost. Local latencies add because the models run one after the other on one machine. The review rule (each run's own 0.70 threshold) applies to whichever answer is used.

| Strategy | Accuracy | Confident-but-wrong | Review rate | Sent to Claude | Evidence recall | Latency median / p90 | Cost per 1,000 |
|---|---|---|---|---|---|---|---|
| All qwen4b_v2 (local only) | 96% | 3.8% ✓ | 0% | 0% | 69% | 5.3s / 8.2s | $0.00 |
| All qwen9b_v1 (local only) | 96% | 3.8% ✓ | 1% | 0% | 70% | 11.7s / 17.4s | $0.00 |
| All Claude | 98% | 0.0% ✓ | 14% | 100% | 83% | 2.5s / 6.3s | $8.57 |
| qwen4b_v2; to Claude if confidence < 0.90 | 94% | 4.1% ✓ | 8% | 12% | 71% | 5.6s / 8.5s | $1.32 |
| qwen4b_v2; to Claude if confidence < 0.95 | 96% | 1.4% ✓ | 11% | 31% | 76% | 6.6s / 11.8s | $3.03 |
| qwen4b_v2 + qwen9b_v1 agree; else Claude | 98% | 2.5% ✓ | 0% | 2% | 69% | 17.7s / 23.4s | $0.29 |
| Agree AND qwen4b_v2 confidence ≥ 0.90; else Claude | 95% | 2.7% ✓ | 8% | 15% | 71% | 18.2s / 25.0s | $1.61 |

Targets: confident-but-wrong ≤ 5%, review rate ≤ 30%, accuracy ≥ 85%, evidence recall ≥ 80%.

## Errors that slipped through without review

- **All qwen4b_v2 (local only)**: C044 (small: not_as_described 0.9, gold refund_not_processed); C048 (small: subscription_cancelled 0.95, gold refund_not_processed); C056 (small: subscription_cancelled 0.9, gold not_as_described)
- **All qwen9b_v1 (local only)**: C047 (large: refund_not_processed 0.85, gold not_as_described); C048 (large: subscription_cancelled 0.95, gold refund_not_processed); C056 (large: subscription_cancelled 0.85, gold not_as_described)
- **All Claude**: none
- **qwen4b_v2; to Claude if confidence < 0.90**: C044 (small: not_as_described 0.9, gold refund_not_processed); C048 (small: subscription_cancelled 0.95, gold refund_not_processed); C056 (small: subscription_cancelled 0.9, gold not_as_described)
- **qwen4b_v2; to Claude if confidence < 0.95**: C048 (small: subscription_cancelled 0.95, gold refund_not_processed)
- **qwen4b_v2 + qwen9b_v1 agree; else Claude**: C048 (small: subscription_cancelled 0.95, gold refund_not_processed); C056 (small: subscription_cancelled 0.9, gold not_as_described)
- **Agree AND qwen4b_v2 confidence ≥ 0.90; else Claude**: C048 (small: subscription_cancelled 0.95, gold refund_not_processed); C056 (small: subscription_cancelled 0.9, gold not_as_described)

## What worked and what didn't

| Change | Worked? | Evidence |
|---|---|---|
| Prompt v2 on Qwen 4B | ✓ | Accuracy 95% → 96%; ambiguous 83% → 88%; confident-but-wrong 5.1% → 3.8% (now passes); gained a safe threshold range (none → 0.50–0.90) |
| Prompt v2 on Qwen 9B | ✗ | Accuracy 96% → 89%; ambiguous 92% → 75%; confident-but-wrong 3.8% → 9.2%. It over-applied the new rules: 6 new errors, all pushed towards refund or subscription |
| Calibration guidance in v2 | ✗ | Neither Qwen model reported confidence below 0.70 any more often (review rate 0–5%) |
| Evidence in v2 | ✗ | Recall fell for both (4B 75% → 69%; 9B 70% → 66%), possibly because the examples show category and confidence only |
| Confidence routing (4B v2, threshold 0.90) | ✗ | Accuracy fell to 94%: some escalated cases the 4B had right, Claude got wrong |
| Confidence routing (threshold 0.95) | Partly | Confident-but-wrong 1.4%, but 31% of cases go to Claude ($3.03 per 1,000) |
| Agreement routing (4B v2 + 9B v1, else Claude) | ✓ | 98% accuracy (= Claude), 2% to Claude, $0.29 per 1,000 (97% cheaper). Caveats: shared blind spots (C048, C056), only 2 escalations, about 18s latency |
