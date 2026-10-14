# Completed triage project and follow-on scope

Recorded 6 October 2026 from the finished source snapshot and the project summary. Original source commit: `e6e8d9e29f18e7cb65908e4b8943ebd83b51f20f`.

## Existing evidence

The triage assistant classifies a complaint, recommends evidence from 26 IDs, explains using retrieved rules and applies human-review logic. It was evaluated on 80 synthetic cases, labelled blind by Sebastian, with three later corrections under written rules. The data is synthetic and the same cases informed prompt experiments; these results do not establish performance on real disputes.

Source evaluation: [model comparison](triage-reference/results/comparison_v2.md), [routing simulation](triage-reference/results/routing_v2.md), [decision memo](triage-reference/docs/decision_memo.md) and [iteration log](triage-reference/docs/iteration_log.md). These are historical source documents; links within them may refer to the original repository. Pricing and model claims are recorded historical assumptions, not freshly verified vendor guidance.

Claude met the original targets on the corrected labels: 98% category accuracy, 0% confident-but-wrong, 83% evidence recall and 14% review rate. Qwen 4B v2 and 9B v1 both reached 96% category accuracy but only 69% and 70% evidence recall. Prompt v2 reduced 9B accuracy to 89%. Agreement routing matched Claude's rounded accuracy with 69% evidence recall; it relied on two escalations and retained shared blind spots. Routing was simulated offline from saved outputs.

## New product hypothesis

Extend the workflow from “which evidence is relevant?” to “which relevant evidence is still missing, and what question would resolve uncertainty?” Inspecting an evidence manifest may reduce repeated requests. It will not automatically recover evidence items omitted by triage, establish evidence adequacy or determine the merits of the claim.

Keep the first version to one agent, three read-only tools, a clarification turn and a fixed-checklist comparator. Use observable missing facts, contradictions and unsupported citations as review triggers. Model-reported confidence alone is insufficient.

## Evaluation decisions still to make

- Choose whether the agent starts from saved Claude triage predictions, live triage or a controlled common input. Give comparisons equivalent inputs and disclose upstream effects.
- Measure relevant missing-evidence recall, unnecessary requests, clarification correctness, supported citations, failures and latency separately from classification accuracy.
- Include expected evidence independently of the triage recommendation so upstream omissions remain visible.
- Evaluate complete, missing, ambiguous and contradictory cases. Ten initial fixtures are development checks; reserve separate cases before making broader performance claims.
- Test Qwen tool use and gap quality before choosing a default. The triage results do not decide agent-task performance.

## Provenance

`source-snapshot.json` records the refreshed source and previous snapshot. The original `baseline/qwen-step-1.jsonl` and its manifest remain unchanged. That run used the earlier code and remains a useful failure example; it is not a new result from the finished snapshot.
