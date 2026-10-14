# What each product guard is worth

**Date:** 7 October 2026 · **Batch:** `batch-20261007T151201Z` (18 runs) · **Data:** 12 development cases, frozen set `6cdaadd3fd1d` · **Model:** qwen3.5-4b, temperature 0 · **Scorer:** rubric v4

The agent drafts; code decides whether a draft may be saved. Five guards refuse drafts that would be costly if a reviewer approved them unnoticed. Each guard was added after an observed failure. This batch measures what each one actually contributes, by running the full system and the system with each guard removed in turn, three times each, interleaved (A B C … A B C …) so that machine drift affects every configuration equally.

## Results

| Configuration | Full passes per run | Harmful outcomes per run | What changes without the guard |
|---|---|---|---|
| All guards on | 9, 9, 9 of 12 | 0, 0, 0 | — |
| Without **delivery** (not-received defence needs delivery proof) | 9, 9, 9 | 0, 0, 0 | Nothing: the guard never fired |
| Without **order link** (payment and order must be provably the same) | 7, 7, 7 | 1, 1, 1 | Defends a case whose payment cannot be tied to the order; and a correct defence loses its linking evidence |
| Without **refund status** (accepting needs the refund position) | 9, 9, 9 | 1, 1, 1 | Accepts a dispute that may already have been refunded: the customer could be paid twice |
| Without **address** (different delivery address needs the customer's earlier request) | 8, 8, 8 | 1, 1, 1 | Defends a parcel sent elsewhere, on the strength of the customer's own later message |
| Without **amounts** (amounts must be on the cited records) | 9, 9, 9 | 1, 1, 1 | An invented figure reaches the evidence pack |

*Harmful outcome:* a wrong defend or accept, or an amount no record supports — what would cost the merchant if approved. A case left without a draft counts as a failure, not a harm.

No case changed result between repeats of the same configuration (0 of 12 in every configuration).

## Decisions

1. **Keep order link, refund status, address and amounts.** Each prevents exactly one harmful outcome per run on the development set, and none blocks a correct decision.
2. **Pass rate alone would have removed two good guards.** Without the refund-status or amounts guard the pass count is unchanged (9 of 12), because the affected case fails either way. The difference is *how* it fails: paying a customer who may already have been refunded, or sending an invented figure, versus stopping short. Evaluation reports harmful outcomes beside pass rate from now on.
3. **Keep the delivery guard, marked dormant.** It never fired with this model and prompt, so it has no measured benefit here — but it also has no measured cost (no refusals at all), and it covers the most common dispute type. It is re-evaluated whenever the model or prompt changes, and on the held-out run. A guard that starts refusing correct drafts would be removed.
4. **Variation lives between sessions, not within a batch.** Earlier, single runs on different occasions differed on 3 of 12 cases with identical inputs; within this batch, 18 runs showed none. Changes are therefore compared only inside one interleaved batch, with the current system as a control in every batch, and a decisive result is replicated in a second batch before it is adopted.

## Remaining failures (all guards on)

| Case | Failure | Candidate change under test |
|---|---|---|
| Partial refund overlap | The model invents item prices; the amounts guard refuses them and the case stops without a draft | `amount_message_v2`: name the figures to remove |
| Cancellation timestamps (wait) | Tries to state absences ("no refund exists") as claims with nothing to cite | `unknowns_field`: a place in the draft for facts no record establishes |
| Cancellation timestamps (defend) | Defends without citing the delivery scan | `delivery_any_defence`: a physical-goods defence must cite the delivery record |

Candidates are switched on one at a time against the current system in a single batch, and only a winner is promoted to the default.

## Candidate fixes — batch-20261007T212510Z

Each candidate was switched on alone against the current system (control) in one interleaved batch, one run each.

| Configuration | Full passes | Harmful outcomes | Effect on its target | Other effects | Decision |
|---|---|---|---|---|---|
| Control | 9 of 12 | 0 | — | — | — |
| `unknowns_field` | 6 of 12 | 1 | Fixed the sourceless-absence drafts, and the timestamp defence | The agent recorded open questions as "unknowns" instead of asking for them; one case defended where it should have waited; two cases ran a model step past the time limit | **Rejected** |
| `delivery_any_defence` | 10 of 12 | 0 | The timestamp defence now cites the delivery scan | None | **Adopt after replication** |
| `amount_message_v2` | 9 of 12 | 0 | The partial-refund case now finishes with the correct decision and supported amounts, instead of stopping without a draft | None; the case still fails one check on how its question is labelled (open label review) | **Adopt after replication** |

**Why the unknowns field was rejected.** It solved the problem it targeted — the agent stopped forcing unknowns into claims — but gave the agent a cheaper exit than asking: it wrote the missing fact down and moved on. The problem it addressed costs retries; the side effect costs wrong decisions. The original behaviour stays, and the refusal message remains the mechanism.

**Timeouts count against the configuration.** A model step that runs past the 180-second limit is a cost of that configuration, not a machine failure, so it is scored as a failed case. (Batch tooling now records it that way; the two timeouts above were first logged as infrastructure errors and are re-scored as failures.)

**Replication.** Both winners, and the two together, are rerun against the control in a second batch before they become defaults.

## Replication — batch-20261007T233824Z

| Configuration | Full passes | Harmful outcomes | Median seconds per model step |
|---|---|---|---|
| Control | 7 of 12 | 0 | 20.9 |
| `delivery_any_defence` | 8 of 12 | 0 | 28.7 |
| `amount_message_v2` | 9 of 12 | 0 | 12.6 |
| Both together | **10 of 12** | 0 | 12.6 |

The first two runs executed at roughly half the machine's normal speed (12–15 seconds per step on every other run), with one model step timing out in each. Their results differ from every earlier run of the same configuration, so they are treated as unreliable rather than as evidence about the changes. The comparison tool now records machine speed for every run and flags any run more than 1.5 times slower than the fastest in the comparison. (One run in the ablation batch is also flagged; its results matched its two repeats exactly.)

The two runs made under normal conditions reproduce the first batch: `amount_message_v2` alone gives the same 9 of 12 with the same failures, and the two changes together give 10 of 12 — each fixing its own case, with no interaction and no harmful outcome.

**Decision: both adopted as defaults.** `delivery_any_defence` becomes the sixth guard, `delivery_cited` (a physical-goods defence must cite the delivery record the case holds); `amount_message_v2` becomes the amounts refusal. The next batch runs the new default as its control, so it serves as the replication; if it does not reproduce 10 of 12, the change is reverted. Neither change blocks a correct decision on any development case.

## Reversal test and second model — batch-20261008T084446Z (14 runs)

Every guard switched off in turn, on both qwen3.5-4b and qwen3.5-9b-mlx, models and configurations interleaved.

| | qwen3.5-4b | qwen3.5-9b-mlx |
|---|---|---|
| Full passes, all guards on | **10 of 12** (reproduces the promoted default) | 4 of 12 |
| Harmful outcomes, all guards on | **0** | 2 (a wrong accept, a wrong defence) |
| Total time for 12 cases | ~20 minutes | ~44 minutes |
| Removing order link / refund status / address / amounts | +1 harmful outcome each (replicates) | +1 harmful outcome for order link, refund status and amounts |
| Removing delivery_cited | −1 pass (the timestamp defence loses its delivery scan) | no change |
| Removing delivery (13.1) | no change — still dormant | no change |

**The larger model is worse here, and slower overall despite faster steps.** Its main failure is a loop: after asking the merchant a question it re-reads the case until the 20-action budget runs out, without saving a draft (5 of 12 cases). The prompt, tools and guards were developed against the 4B model; the 9B result shows how much of the system's behaviour is tuned to the model it was built on.

**The second model found two gaps no guard covered,** because the 4B model never made these mistakes:
- Accepting a dispute where part of the payment was already refunded (£500 of £900) — accepting returns the full amount, paying the refunded part twice. The refund-status guard only checked that the refund position was cited, not what it said.
- Defending a cancellation dispute when the merchant's own records show the cancellation arrived (09:45 UTC) before the payment was taken (10:00 UTC).

**Decisions.** Keep the 4B model for development. Test three candidates next, on both models, against the current system: `loop_guard` (a third identical read call is refused, with the next step stated), `partial_refund_accept` and `cancellation_timeline` (the two missing guards). Neither new guard blocks a correct decision on any development case. Machine-speed flags now compare each run with others on the same model.

## Guards for the gaps the second model found — batch-20261008T165627Z (10 runs)

| Configuration | 4B passes | 4B harmful | 9B passes | 9B harmful |
|---|---|---|---|---|
| Control | 10 | 0 | 4 | 2 |
| `loop_guard` | 10 | 0 | 5 | 2 |
| `partial_refund_accept` | 10 | 0 | 4 | 1 (wrong accept removed) |
| `cancellation_timeline` | 10 | 0 | 5 | 1 (wrong defence removed) |
| All three | 10 | 0 | **6** | **0** |

On the 4B model none of the three changes anything — it never made these mistakes — and none caused a regression. On the 9B model each guard removes exactly the harmful outcome it was written for, the loop guard turns one budget-exhausted case into a pass, and together they remove every harmful outcome.

The two 9B runs with the loop guard show slower steps (15–17 seconds against 6). The runs either side on the same model were at normal speed, so the configuration, not the machine, is the cause: refused repeat calls lengthen the conversation. Total time still fell (about 30 minutes against 33), because fewer actions are wasted. The comparison tool now tells these cases apart.

**Decision: all three adopted as defaults** — as guards `loop`, `partial_refund` and `cancel_timeline`, each switchable for measurement. Nine guards in total; none blocks a correct decision on any development case. The 4B model stays the development model: 10 of 12 against the 9B's 6 of 12, in roughly half the time.

## Pause and resume, with every guard ablated — 9 October 2026

Batches `batch-20261009T001752Z` and `batch-20261009T083854Z` (qwen3.5-4b, run in separate sessions) and `batch-20261009T032726Z` (qwen3.5-9b-mlx, 6 of 10 configurations completed). Three development cases now receive a late record after the agent pauses, and their final decision is scored.

**qwen3.5-4b — both sessions gave identical results, case by case:**

| Configuration | Full passes | Harmful outcomes |
|---|---|---|
| All nine guards on | 9 of 12 | 0 |
| Without order link | 7 | 1 (wrong defence) |
| Without refund status | 10 | 1 (wrong accept) |
| Without address | 8 | 1 (wrong defence) |
| Without amounts | 9 | 1 (invented amount) |
| Without delivery_cited | 8 | 0 |
| Without delivery, partial refund, cancellation timeline or loop | 9 | 0 |

**qwen3.5-9b-mlx (completed configurations):** all guards on 5 of 12, 0 harmful outcomes; removing order link, refund status or partial refund each brings back one harmful outcome. Partial refund protects on this model and not on the 4B, as expected.

**Resumed cases (4B).** Two of three reach the correct final decision once the late record arrives (a carrier confirms delivery → defend; a refund confirmation arrives → defend). In the third, the carrier reports the parcel lost: the agent proposes the expected outcome, accepting the dispute, and the refund-status guard refuses it because no record shows whether the customer was already refunded. The agent then asks for the refund status and waits. The evaluation label expects an immediate accept; the guard applies the stricter rule that a merchant should not accept until it knows it has not already refunded. This is a policy disagreement between the product rule and the label, not an agent error, and is recorded for the label review rather than resolved by changing either.

**Runs excluded.** From 14:00 on 9 October, three batches were started at once on the same model server. Every run slowed by a factor of three or more and many hit the step time limit; all runs from those batches are excluded. Batches now take a lock: a second batch refuses to start while one is running. Each batch also writes its own log to `logs/`.

**Policy decision (11 October).** The product owner decided the stricter rule stands: before accepting a dispute, the merchant must know it has not already refunded the customer, even when a carrier confirms the parcel lost. The lost-parcel case's expected answer is amended accordingly (ask for the refund status, then wait), recorded in a separate amendments file with the decision, date and reason; the frozen answers are not edited. Under rubric v5 the 4B with resume scores **10 of 12 with 0 harmful outcomes** in both sessions.

**Gaps found after the ablation (12 October).** Three wrong decisions passed every guard: a response drafted for an order cancelled before dispatch with no refund record (single agent, two cases), an acceptance of a dispute already refunded in full (9B), and a response drafted while the customer said they had asked their bank to withdraw the dispute (every method, both held-out cases). The ablation measures what each existing guard prevents; it cannot show what no guard covers. The three proposed guards are listed in [held-out-results.md](held-out-results.md#decision) and will be measured on a fresh held-out set.
