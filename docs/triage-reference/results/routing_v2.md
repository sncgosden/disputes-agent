# Routing simulation (offline, from saved results)

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
