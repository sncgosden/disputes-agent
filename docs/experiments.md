# Agent experiments log

Each experiment changes one thing, states its hypothesis and prediction before the run, and is judged on the full development suite (12 cases, 9 contrast pairs) against the previous suite with every other fingerprint unchanged. Held-out cases are not used for tuning. Model: qwen3.5-4b, temperature 0. Temperature 0 did not make runs identical across sessions (3 of 12 cases differed between occasions with identical inputs), so from S5 onward changes are compared only inside one interleaved batch with a control run (see [guard ablation](guard-ablation.md)).

Results use rubric v4 unless stated (changelog: `docs/evaluation-rubric.md`). "Gate-helped" means a readiness guard refused a draft at least once before the case passed.

## Summary

| Suite | Single change | Full passes | Unaided | Gate-helped | Decision now correct |
|---|---|---|---|---|---|
| Baselines | Always defend / always wait | — | — | — | 4/12 / 6/12 |
| S1 `suite-20261007T114428Z` | First full run (delivery and ID-link guards already in place) | 8/12 | 6/12 | 2/12 | 10/12 |
| S2 `suite-20261007T121913Z` | Accepting needs the refund position on record | 8/12 | 6/12 | 2/12 | 11/12 |
| S3 `suite-20261007T125002Z` | A different delivery address needs a pre-delivery customer request | 9/12 | 6/12 | 3/12 | 12/12 |
| S4 `suite-20261007T133429Z` | Clearer error for claims citing nothing | 9/12 | 6/12 | 3/12 | 12/12 |
| S5 | Claim amounts must be supported by cited records | 9/12 | — | — | 12/12 |
| Later | Guard ablation, delivery citation, loop guard, partial refunds, cancellation timeline, pause and resume, configuration comparison, held-out run | see [guard ablation](guard-ablation.md), [configuration comparison](configuration-comparison.md), [held-out results](held-out-results.md) | | | |

Under the original scoring (rubric v2) S1–S3 were 6/12 full passes; the move to 8–9 comes from re-scoring the same traces after tool selection was found to score labels rather than behaviour. It is a measurement correction, not an agent improvement.

## S2 — refund position before accepting
- **Failure (S1, MC-c7d1c0083d):** accepted a dispute without checking whether a refund had already been issued.
- **Cost:** the customer can be paid twice (refund plus chargeback).
- **Change:** a draft recommending acceptance must cite a refund record or a ledger search; if the case has none, the refusal says to ask for refund status and wait.
- **Pre-run check:** across all 12 development cases the guard blocks no correct decision.
- **Prediction:** only MC-c7d1c0083d changes, to "wait". **Result:** as predicted; the other 11 cases identical.

## S3 — address conflicts
- **Failure (S1–S2, MC-aa077ca73b):** defended a parcel delivered to a different address, using the customer's after-the-fact message as proof.
- **Cost:** a lost dispute plus fees; untrusted text treated as evidence.
- **Change:** when the delivered address differs from the order address, defending needs a customer request made before delivery; otherwise the case is escalated to a person.
- **Pre-run check:** no correct decision blocked; defence now refused on 4 of the 8 cases where defending is wrong.
- **Prediction:** MC-aa077ca73b escalates; its contrast case still defends. **Result:** as predicted; decision correct 12/12.

## S4 — claims that cite nothing (hypothesis not supported)
- **Failure:** the agent repeatedly states absences ("no refund exists") with no source, and the draft is rejected.
- **Change:** the rejection explains that an absence needs a search record, otherwise it is unknown.
- **Result:** no outcome changed. The model invented a record ID to cite (refused), then stated "status unknown" as another sourceless claim. The message gave it nowhere to record an unknown. **Next:** a structural fix — an explicit field for open unknowns in the draft.

## S5 — amounts supported by cited records
- **Failure:** invented figures in claims (£12,500 for a £125.00 payment; item prices that appear in no record). Previously caught only by the scorer, after the fact.
- **Cost:** a misrepresented evidence pack sent to the card network.
- **Change:** the same rule now runs when a draft is saved: every amount must be on a cited record, or a difference or sum of two of them (e.g. a remaining balance).
- **Pre-run check:** replayed against all 61 drafts saved to date, it refuses exactly the 7 with known wrong amounts.
- **Prediction:** MC-a08605886c is refused on invented prices and resaves with supported figures; other cases unchanged.
- **Result:** partly as predicted. The guard refused the invented prices, but the case then stopped without a draft; a revised refusal that names the figures to remove let it finish with supported amounts. In the ablation, removing the guard adds one harmful outcome per run (an invented figure reaches the evidence pack) with no change in pass rate. **Adopted.**

## Open items
- MC-a08605886c asks for a "refund record" where the label expects the "provider ledger": a proposed label correction awaiting review; the frozen label is unchanged.
- Three gaps no guard covers, found after these experiments: see [held-out results](held-out-results.md#decision).
