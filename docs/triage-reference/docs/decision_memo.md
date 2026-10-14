# Decision memo: dispute-triage assistant

**Recommendation:** ship **Option A, Claude with human review**, to a pilot group of small merchants. Plan **Option B, local agreement routing**, as the scale-up path once real merchant data confirms its signal.

All numbers: 80 synthetic cases, labelled by me, scored on corrected labels (`results/comparison_v2.md`, `results/routing_v2.md`). One case = 1.25 points of accuracy.

## The decision

| | A. Claude + review (**launch**) | B. 4B + 9B agree, else Claude (**scale-up**) |
|---|---|---|
| Category accuracy (ambiguous cases) | **98%** (92%) | **98%** (92%) |
| Confident-but-wrong (target ≤ 5%) | **0%** | 2.5% |
| Sent to human review | 14% | 0%* |
| Evidence recall (target ≥ 80%) | **83%** ✓ | 69% ✗ |
| Latency median / p90 (p90 target ≤ 10s Claude, ≤ 20s local) | **2.5s / 6.3s** ✓ | 17.7s / 23.4s ✗ |
| Cost per 1,000 cases | $8.57 | **$0.29** |
| Data leaving the device | 100% of cases | **2%** |

\*B's review rule rarely fires, because the local models gave every answer between 0.85 and 0.95 confidence. Its safety comes from the agreement check, not from review.

**Why A for launch:** it's the only option that meets every PRD target, including evidence quality, which is what a merchant actually submits. It's also the fastest and the simplest to run. At **under 1p per dispute**, cost doesn't matter for a merchant with a few disputes a month.

**Why not B yet:** it matches A on category but **misses the evidence target** and the p90 latency target (23s against 20s), and its 98% rests on only 2 escalations (C044, C047). It also has **shared blind spots**: C048 and C056 got through because both local models were wrong in the same way. It becomes the better choice when volume, cost or data residency matter more, and once real data confirms the agreement signal.

## Target merchants

Small UK online merchants (e-commerce, services and bookings, subscriptions) handling a few disputes a month without a payments or risk team. Not for high-volume merchants, who already use dedicated dispute tools, or mainly card-present businesses, where there's little evidence to recommend.

## Human-review threshold

Send a case to a person if **any** of these is true: confidence < **0.70**, top two categories within 0.15, model says `unclear`, no rule section retrieved, or invalid output.

For Claude, 0.70 sits inside the safe range (0.50–0.87): **0 confident errors, 14% review**. Every Claude error in testing was flagged. **The threshold must be recalibrated for any other model.** The same rule caught almost none of the Qwen models' errors (0–5% review), because every Qwen answer scored 0.85 or above. The merchant always approves before anything is submitted. The tool recommends; it never files.

## Failure modes seen in testing

1. **Complaints with two claims** ("poor service *and* the refund never came"): half of all first-round errors (8 of 16, on the original labels). Mitigated by a claim-priority rule (refund promised > recurring charge > the goods or service). The cost: the same rule made the 9B over-apply it (96% → 89%).
2. **Recurring vs one-off charges** (a second "pack" charged after notice).
3. **Evidence lists that are long and unfocused:** precision 38–50%. Merchants may submit irrelevant documents.
4. **Ambiguous labels:** 3 of 80 gold labels changed under written rules after the first runs. Real disputes will be messier.

## Guardrails

- A fixed vocabulary of 26 evidence IDs (**0 invented IDs across all 400 answers in the five full runs**).
- Explanations must cite rule sections; citations to sections not provided are logged.
- JSON validation with one retry: **100% valid output**.
- Monitor weekly: review rate (alert above 30%), human overturn rate, and the share of multi-claim cases.

## Data handling

Option A sends the complaint text, merchant type, amount and date to the Anthropic API; no card numbers or account details are needed. Before a pilot: strip customer names, emails and order numbers; confirm Anthropic's commercial data-retention terms; tell merchants in the terms of use. Option B keeps 98% of cases on the merchant's or provider's own hardware.

## Provenance and licence

- **Models:** Claude Sonnet 5.5 (Anthropic, commercial API, $2 / $10 per million tokens, checked 5 Oct 2026); Qwen 3.5 4B and 9B (Alibaba Qwen team, Apache 2.0; 9B licence to confirm on its model card); nomic-embed-text v1.5 (Nomic AI, Apache 2.0).
- **Data:** synthetic cases only; rules summarised from public Visa and Mastercard guidance.

## What would change my mind

- **Ambiguous-case accuracy below 80% on real data:** send all multi-claim complaints to a person by default.
- **Agreement routing at ≥ 97% accuracy on 300+ real cases, with both local models giving the same wrong answer in under 2% of cases, and evidence fixed:** switch to B.
- **A merchant or provider who can't send data to a US API provider:** B becomes the only option, with Claude replaced by human review for disagreements.

## Next tests

1. **Real merchant disputes** (300+, anonymised), with a held-out test set; then a pilot measuring dispute win rate, merchant time per dispute and human overturn rate.
2. **Fix evidence:** Claude-generated checklists with local classification, or evidence-focused examples.
3. **Agreement routing across different model families**, to reduce shared blind spots.
4. **Claude with prompt v2**, to check whether the claim-priority rule helps or hurts the strongest model.
