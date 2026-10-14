# Held-out evaluation plan (registered before the run)

**Registered:** 12 October 2026, before the held-out cases were run by any configuration. The exact code, prompt and scorer are fingerprinted in `realworld/results/held-out-freeze.json`; the run refuses to start if any of them differ, and refuses a second run unless a reason is given and recorded.

**What runs.** The six held-out cases (duplicate customer profiles, a late provider status, injected instructions — two of each), once, with qwen3.5-4b, all nine guards on, pause-and-resume on, rubric v5, for each of three methods: single agent, team, fixed checklist.

**How the reported configuration is chosen.** The method with the most full passes on the development cases in the batch run immediately before the held-out run, among methods with zero harmful outcomes; ties go to the faster method. All three held-out results are reported whichever is chosen. Held-out results are never used to choose or change anything; any change after this point needs a new held-out set.

**What is reported.** For each method: full passes, decision now, final decision after late records, harmful outcomes, security flags on the two injection cases, time and tokens — as counts out of six, with no percentages. Six cases can show whether a result generalises beyond the development set; they cannot establish production accuracy.
