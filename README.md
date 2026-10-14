# Dispute Case Preparation Agent

Helps small online retailers selling physical goods prepare chargeback cases. The agent investigates a dispute across payment, order, delivery, refund and customer records, checks the card network's published guidance, and prepares a cited case for a person to review. It asks for missing facts instead of guessing, and nothing leaves the system without human approval of the exact evidence.

## Findings

- **The held-out set changed the decision.** A fixed rules checklist scored 11 of 12 on the development cases and was chosen by a rule registered before the held-out run. On six new cases it scored 2 of 6, as did the single agent. Every harmful outcome came from one unseen pattern: a customer's unverified claim that the dispute was withdrawn.
- **Rules and the model fail in different places.** The checklist handled structured records and missed free text; the agent was the only method to pass both injected-instruction cases. The next design is rules first, with the model turning free text into facts the rules consume and unmatched cases escalating to a person.
- **A specialist team did not earn its cost.** Once its orchestration was fixed it matched the single agent on decisions but completed 1 of 12 cases at 2.5 times the tokens and time.
- **Pass rate alone would have removed good guards.** Removing the refund-status or amounts guard leaves the pass count unchanged but adds a harmful outcome each run, so harmful outcomes are reported beside pass rate throughout.
- **Cost is human time, not tokens.** About £0.12 of hosted-model tokens per case; the economics depend on review minutes and correctness.

## Status

| Area | State |
|---|---|
| Payment integration | Stripe test mode: signed webhooks, dispute deadlines, staging, approval bound to the exact payload, single submission |
| Guidance | 11 official network and provider sources, versioned, with citations verified against the captured text |
| Evaluation data | 18 generated cases in 9 contrast pairs (12 development, 6 held out), frozen as `6cdaadd3fd1d`; expected answers kept separate |
| Tools | 11 tools in four permission levels (read, prepare, ask, propose); merchant-scoped; idempotent writes; bounded retries |
| Agent | Single agent on a local model (Qwen 3.5 4B via LM Studio) with nine code-enforced guards |
| Results | Held out, run once on a registered configuration: no method generalises — 2 of 6 for the chosen fixed checklist and for the single agent, 0 of 6 for the team, with 2 harmful outcomes each, all from one pattern none of them handles. See [held-out results](docs/held-out-results.md), [configuration comparison](docs/configuration-comparison.md) and [guard ablation](docs/guard-ablation.md) |
| Configurations | Single agent; a team of specialist sessions (investigator, rules analyst, response specialist, reviewer) coordinated in code; and a fixed rules checklist with no model, all scored on the same cases |
| Pause and resume | A waiting case resumes in a fresh session when the missing record arrives; the final decision is scored separately |
| Security | The preparing agent cannot propose external actions; a code screen flags instruction-like text in customers' words for a person; a probe plants instructions, data requests and false evidence: 10 of 12 probes fully passed, 12 of 12 flagged, no external action proposed |
| MCP server | Read-only, over stdio: case, record, search, events and guidance tools for one merchant fixed at start-up; returns exactly what the agent's own tools return |
| Review screen | One page per prepared case: each claim beside the records it cites, the records it leaves out, what the checks refused, security flags and cost |
| Unit economics | Cost per correctly prepared case from measured runs and stated assumptions about human minutes, with the review time the product must beat |
| Next | Rules first, model for the residue: rules decide what records settle, the model turns free text into facts the rules consume, unmatched cases escalate. Three new guards and a fresh held-out set (see [held-out results](docs/held-out-results.md#decision)); timed human review minutes |

## How decisions are controlled

The model proposes; code decides what may be saved. A draft is refused if it would defend a non-delivery claim without delivery proof, defend physical goods without citing the delivery record the case holds, defend a payment that cannot be tied to its order, accept a dispute without knowing whether a refund was already issued, defend a parcel delivered to a different address without the customer's earlier request, accept a dispute that was already partly refunded, defend a cancellation the records show arrived before payment, or state an amount its cited records do not contain. Repeating the same lookup a third time is refused with the next step stated. Refusals tell the agent which record to cite, or to ask and wait. Proposals to act externally wait for a named person and never execute themselves.

## Running it

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python realworld/scenarios.py generate   # rebuilds the 18 cases from their seed; records hash 6cdaadd3fd1d
python realworld/guidance.py fetch       # captures the published guidance
```

Checks that need no model:

```sh
python -m case_agent.check_read_tools
python -m case_agent.check_write_tools
python -m case_agent.check_boundaries_recovery
python -m case_agent.check_guards_overblock
python -m case_agent.check_mcp_parity
python realworld/score_case.py --self-test
```

With LM Studio serving the model locally:

```sh
python -m case_agent.agent --case MC-7f29dad220 --model qwen3.5-4b      # one case
python -m case_agent.run_suite --model qwen3.5-4b                       # all development cases
python -m case_agent.run_suite --model qwen3.5-4b --repeats 3 --ablate  # each guard switched off in turn
python -m case_agent.run_suite --model qwen3.5-4b --methods agent,team,checklist --resume  # three configurations
python -m case_agent.security_probe --model qwen3.5-4b                  # planted-instruction probe
python -m case_agent.compare_suites SUITE_ID [SUITE_ID ...]             # case-by-case comparison
```

Reviewing and costing saved runs (no model needed):

```sh
python -m case_agent.review_screen --run SUITE_ID                       # pages in reviews/SUITE_ID/
python -m case_agent.cost_model SUITE_ID [SUITE_ID ...]                 # cost per correct case
python -m case_agent.mcp_server --merchant merchant_a                   # read-only MCP server on stdio
sh scripts/fresh_setup_check.sh                                         # rebuild from a clean clone and run all checks
```

Held-out cases run once, on a frozen configuration, and only with `--confirm-held-out`.

## Layout

| Location | Purpose |
|---|---|
| `case_agent/` | Tool contracts, read and write tools, executor, model adapter, agent loop, suite runner |
| `realworld/` | Stripe bridge, guidance capture and retrieval, case generator, scorer; `results/` holds saved runs |
| `docs/` | Product requirements, architecture, metrics, evaluation rubric, decisions and results |
| `reviews/` | Generated review pages (not committed) |
| `reference/triage/` | Earlier triage classifier reused for comparison |
| `baseline/` | Original baseline input and output, kept as historical evidence |

Generated cases and results describe behaviour on synthetic records; they are not production accuracy or measured merchant savings.
