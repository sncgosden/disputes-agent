# Failure taxonomy

Every failed run is assigned one primary failure class before anything is changed. The class decides the fix; fixing the wrong class (for example, rewriting a prompt to compensate for a retrieval gap) hides the problem and usually creates a new one.

| Class | What goes wrong | Example already observed in this build | Usual fix |
|---|---|---|---|
| **Data and environment** | The system is pointed at the wrong account, version or dataset, or the test data is impossible | Stripe CLI attached to a different sandbox, so events never arrived; a generated cancellation that preceded its own order | Identity checks across components; data validation before use |
| **Leakage** | The agent can see the answer through IDs, names or metadata | Profile named `other_…`; pending event IDs naming the record about to arrive | Opaque IDs; a standing "can the agent see the answer?" check |
| **Retrieval** | The right passage exists but is not returned, or the wrong one ranks first | "Refund never processed" missed Visa's "Credit Not Processed"; Visa 13.3 ranked above 13.1 | Vocabulary mapping, section-aligned passages, applicability filters, hybrid search |
| **Source** | A source moved, changed or cannot be accessed | Mastercard guide returned 404 at its old address; one merchant account not retrievable | Official-source capture with hashes; all-or-nothing refresh; downgrade unverifiable evidence |
| **Context** | Relevant evidence was retrieved but dropped, truncated or drowned before the decision | Not yet observed; expected with small local context windows | Context budgets, manifests per call, preserved source IDs |
| **Tool** | Wrong tool, wrong arguments, a schema rejection or an unhandled tool error | Not yet observed in agent runs; tool boundaries reject wrong-merchant and path-style IDs | Typed schemas, intent vocabulary, bounded retries with recorded errors |
| **Plan and judgement** | The agent decides before fetching an obtainable record, or ignores a record it fetched | Human labelling: four decisions made on missing evidence (for example accepting a £900 dispute after a £500 refund) | Decision boundaries in instructions and readiness checks; contrast cases in evaluation |
| **Memory and state** | Progress lost on restart, an event processed twice, or a resolved case rolled back | Avoided by design: duplicate and out-of-order Stripe events produced one case | Persist before acknowledging; refresh provider state; release late records once |
| **Timing** | A race or timezone error changes the conclusion | Processing ran seconds before webhooks arrived; local times that look earlier are later in UTC | Never conclude from one empty check; compare parsed UTC times |
| **Safety and permissions** | An injected instruction is followed, a boundary is crossed or an action is taken without approval | Attack text placed in a customer message and a carrier note; no tool exists that could act on it | Least privilege, payload-bound approval, untrusted-text envelopes, security flag |
| **Evaluation** | The measurement is wrong rather than the system | Answer key missed an overlapping passage (q09); baseline quoted for the wrong decision point (12/18 versus 8/18) | Reviewed labels, logged corrections, recheck baselines before quoting |
| **Cost and latency** | The run is correct but too slow, too expensive or over budget | Not yet observed | Budgets with recorded stops; cost per correct case including failures |

## Procedure

1. Classify the failure from the trace; record the class, the case and the evidence.
2. State the hypothesis and the single change that tests it before changing anything.
3. Re-run the development set and compare per case: what improved, what worsened.
4. Keep negative results. A change that fixes one class and breaks another is reported as both.
