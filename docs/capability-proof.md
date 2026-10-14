# Capability evidence map

Each capability an agent product depends on, the evidence that exists for it today, and what is still to be shown. "Proven" means an executed result with a saved output; design documents alone do not count.

| Capability | Status | Evidence today | Still to show |
|---|---|---|---|
| **Agent loop** (plan, act, observe, re-plan, stop) | Not started | Decision boundaries and stopping limits specified (20 actions, 40 tool calls, 2 repair cycles, 15 minutes); five cases that need different next moves from the same complaint ([agency boundary](agency-boundary.md)) | A run where an observation changes the next action; enforced limits on a looping case; local model tool-use reliability |
| **Tools and actions** | Partly proven | Stripe test-mode bridge: signed webhooks, current-state refresh, staging with `submit=false`, payload-bound single-use approval, idempotent submission confirmed from the provider. `get_case` scoped to the owning merchant. Guidance `search`, `show` and `verify` | Record search, plan, task and draft tools with typed inputs, errors and retries; a timeout reconciled before any retry |
| **Context engineering** | Not started | Context budget and preservation rules specified in the PRD | Context manifests per call; selected versus broad context compared on cases |
| **Memory and state** | Partly proven | Persisted events and cases; duplicate, out-of-order and missed events handled; late records released once and only when the case is waiting | Resume after restart mid-investigation; merchant answers stored as assertions until supported |
| **Retrieval (RAG)** | Baseline measured | 11 official sources captured with content hashes (4,134 passages); printed pages, reason codes and network metadata; applicability filters; citations checked against captured bytes; 10 reviewed questions: 4/10 found in the top five | Section-aligned passages, provider-to-network vocabulary and hybrid search, each measured against the baseline |
| **MCP integration** | Not started | — | Case and guidance tools exposed over MCP; the same lookup from a second client; scope enforced on the server |
| **Orchestration** | Not started | Specialist roles defined, kept only if measured gains justify their cost | Fixed checklist, single agent and specialist team compared on identical cases and budgets |
| **Evaluation and observability** | Partly proven | Frozen 18-case set in contrast pairs, reproducible from seed; leakage, chronology and late-event checks; blind human labels (5 of 7 independent agreement) with reviewed disagreements; always-respond baselines stated (8 of 18 decisions now, 12 of 18 final recommendations); retrieval baseline saved with corpus version | Per-run traces; agent scored per decision type; regression runs after each change; held-out run once at the end |
| **Guardrails and human approval** | Proven at the tool layer | Merchant scope, path-style ID rejection, untrusted-text envelopes for two injection channels, no export or self-approval capability, approval bound to the exact payload, test and live modes separated | Model behaviour under injection; security flag raised alongside the case decision |
| **Economics and product** | Partly evidenced | Observed dispute economics (£42 sale, £42 withdrawn plus £20 fee); published merchant account of a $1,400 loss on a $900 order from a refund overlap; outcome metric defined as correctly prepared cases per unit of human effort | Cost per successful case including failed attempts and review time; timed comparison against a manual checklist |

## Reading this map

The foundations an agent depends on (a real payment integration with safe irreversible actions, versioned guidance with measured retrieval, and a frozen evaluation set built so that the easy answer fails) were proven first. The agent itself is next. Every result above has a stated baseline to beat, so later claims can be checked rather than asserted.
