# Capability evidence map

Each capability an agent product depends on, the evidence for it, and what remains open. "Proven" means an executed result with a saved output; design documents alone do not count. Status as of 12 October 2026.

| Capability | Status | Evidence | Open |
|---|---|---|---|
| **Agent loop** (plan, act, observe, re-plan, stop) | Proven | Runs on all 18 cases with enforced limits (20 actions, 40 tool calls, 2 repair cycles, step time limit); a loop guard refuses a third identical call; late records change the next action and the final decision | Generalisation: 2 of 6 held-out cases ([held-out results](held-out-results.md)) |
| **Tools and actions** | Proven | 11 tools in four permission levels, merchant-scoped, typed errors, idempotent writes, bounded retries with a check that a timed-out write did not already happen; Stripe test mode with payload-bound, single-use approval | Live provider beyond test mode |
| **Context engineering** | Measured | Compacting tool results cut accuracy from 10 to 4 of 12 and raised tokens by 43%; rejected. Guidance is used in about 1% of tool calls and no failure traced to it ([retrieval priority](retrieval-priority.md)) | Revisit if longer cases exceed the context budget |
| **Memory and state** | Proven | A waiting case resumes in a fresh session from saved state when the missing record arrives; its final decision is scored separately | Merchant answers stored as assertions until supported |
| **Retrieval (RAG)** | Baseline measured | 11 official sources, 4,134 passages, content-hashed; applicability filters; citations checked against captured bytes; 4 of 10 reviewed questions answered in the top five | Improvement deferred on evidence above |
| **MCP integration** | Built | Read-only server over stdio; merchant fixed at start, never a client argument; every answer identical to the agent's own tools (13 of 13 checks) | A second client connected |
| **Orchestration** | Measured | Fixed checklist, single agent and a four-role team on identical cases and budgets: 11, 7 and 1 of 12 on development; 2, 2 and 0 of 6 held out ([configuration comparison](configuration-comparison.md)) | Rules first, model for free text, as the next design |
| **Evaluation and observability** | Proven | Frozen contrast-pair case set reproducible from seed; versioned rubric; per-step traces; guard ablation with replication; harmful outcomes reported beside pass rate; held-out run registered and fingerprinted in advance; review screen built from traces | A fresh held-out set for the next round |
| **Guardrails and human approval** | Proven | Nine code-enforced readiness guards; the preparing agent cannot propose external actions; instruction-like customer text flagged by a code screen; probe: 10 of 12 passed, 12 of 12 flagged, no external action proposed | Screen applied to every method, not only the agent |
| **Economics and product** | Partly evidenced | Cost model from measured runs: about £0.12 of hosted-model tokens per case, so human review time and correctness dominate; the review time the product must beat is computed per configuration | Timed human review on real cases |

## Reading this map

The foundations were proven first: a real payment integration with safe irreversible actions, versioned guidance with measured retrieval, and a frozen evaluation set built so that the easy answer fails. The agent was then built and measured against them, including the configurations that lost. The open items are the ones the held-out result made most important.
