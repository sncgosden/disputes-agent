# Retrieval improvements: deferred

**Decision (11 October 2026):** the planned retrieval improvements (section-aligned passages, vocabulary mapping, hybrid search) are deferred. Retrieval stays measured on its own benchmark; it is not on the path to a correctly prepared case today.

**Evidence.** Across 246 agent traces from the clean 9 October runs (2,225 tool calls), published guidance was searched 12 times and read 12 times — about 1% of calls. No failure in any development case traces back to guidance: every wrong or unfinished case so far comes from how records were read, reconciled or cited. The decisions these cases need are about the merchant's own records, and the rules that matter most are already enforced in code.

**What would change this.** Guidance becomes decisive when a dispute's outcome turns on a network rule the records cannot settle — for example compelling-evidence eligibility (Visa CE 3.0) or time limits by reason code. When cases of that kind are added, or when a team member's role depends on it (the rules analyst in the team configuration), retrieval quality is re-measured against the 10 labelled questions (current baseline: 4 of 10 relevant passages in the top five) before it is improved.
