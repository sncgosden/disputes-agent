# Single agent, team and fixed checklist

**Data:** 12 development cases with pause-and-resume, rubric v5 · **Model:** qwen3.5-4b · **Batches:** `batch-20261011T140022Z`, `batch-20261011T235057Z`

## First run (11 October)

| Configuration | Full passes | Decision now correct | Harmful outcomes | Time | Tokens |
|---|---|---|---|---|---|
| Single agent | **10 of 12** | 12 of 12 | 0 | 15 min | 0.42 M |
| Single agent, compact observations | 4 of 12 | 9 of 12 | 1 | 19 min | 0.61 M |
| Team (investigator, rules analyst, drafter, reviewer) | 0 of 12 | 4 of 12 | 1 | 67 min | 2.08 M |
| Team, compact observations | 0 of 12 | 5 of 12 | 2 | 94 min | 2.68 M |
| Fixed checklist (no model) | **11 of 12** | 12 of 12 | 0 | < 1 s | 0 |

The single agent reproduces its earlier result for the third time.

**Compact observations: rejected.** Trimming tool output (dropping empty fields, shortening free text) cut accuracy from 10 to 4 and *raised* token use by 43%: with less in each observation the model made more calls to find what it needed. Reading less per step is not the same as reading less in total.

**Team: the result reflects a defect in how the team was run, not the team design.** A session ended only when it saved a draft, so the investigator and rules analyst — whose job ends when they save their findings — kept working until their 20-action budgets ran out, then timed out on long conversations (five cases) or handed incomplete findings on. The coordinator now ends each specialist's session when its own deliverable is saved. The team runs again against the single agent in one batch before any conclusion is drawn about teams.

**Fixed checklist: 11 of 12, instantly, with no model.** It was written after studying these cases and cannot read free text; both it and the chosen agent configuration run once on the six held-out cases, frozen, which include the kinds of case a checklist cannot see (duplicate customer profiles, a late provider status, injected instructions).

## Security probe (11 October)

Three attacks — a fake system instruction, a request for other customers' data, and false evidence claiming to come from the merchant — planted in the customer message of four development cases (12 probes).

| Check | Passed |
|---|---|
| Stayed within the case | 12 of 12 |
| No external action proposed | 11 of 12 |
| Decision unchanged | 8 of 12 |
| Security flag raised | 6 of 12 |

**Findings and changes.**
- *The fake instruction led the agent to call `propose_action`.* Nothing would have happened — proposals never execute and wait for a named person — but preparing a case should not involve proposing actions at all. **The agent no longer has that tool** (least privilege); a person starts a proposal from the reviewed draft.
- *The agent flagged only half the attacks.* A deterministic screen now flags free text that reads like instructions to the assistant, asks for other people's data, or claims to speak for the merchant. It flags the case for a person and never changes the decision; it flags none of the twelve development cases' genuine messages.
- *Probe design error, corrected.* The first probe replaced the customer's message with the attack. In the address-conflict case that message is evidence, so replacing it changed the correct answer and three "failures" there were the probe's fault. Attacks are now appended to the original message.

## Second run, after the fixes (12 October)

Same cases, same rubric, one batch, the team's coordinator now ending each specialist's session when its deliverable is saved, and the agent without the proposal tool.

| Configuration | Full passes | Decision now correct | Harmful outcomes | Time | Tokens |
|---|---|---|---|---|---|
| Single agent | 7 of 12 | 8 of 12 | 2 | 18 min | 0.48 M |
| Team | 1 of 12 | 8 of 12 | 0 | 45 min | 1.23 M |
| Fixed checklist | **11 of 12** | 12 of 12 | 0 | < 1 s | 0 |

**Team: a fair comparison now, and it loses.** With sessions ending correctly the team reaches the right decision as often as the single agent, but passes only one case: specialists asked questions the records already answered (6 cases) and repeated refused calls (5), each handoff losing context the next role had to rebuild. It costs 2.5 times the tokens and time of the single agent. Splitting the work did not split the difficulty; it multiplied the places to go wrong.

**Single agent: down from 10 to 7, with two harmful outcomes.** Both are cases where a customer cancelled before dispatch, which had passed in every run since 7 October; the agent drafted a response and no guard stopped it. The change in between was removing the proposal tool and adding the screen. One batch cannot confirm the cause; it does show those passes rested on the model, not on a guard.

**Chosen for the held-out run by the registered rule: the fixed checklist.** Results: [held-out-results.md](held-out-results.md).
