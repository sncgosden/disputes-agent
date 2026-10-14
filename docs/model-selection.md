# Model selection

Which local model drives the agent, how tool requests are obtained from it, and what evidence the choice rests on. Raw results: `realworld/results/spike-tool-calls-*.json`.

## Tool-calling spike (7 October 2026)

Three single-step tasks against the real tools (read a case, search its records, save a plan), each request validated against the tool contracts and executed in a temporary workspace. Temperature 0, all 11 tools offered, LM Studio on a MacBook Air.

| Model | Native tool calling | JSON in text | Median seconds per call (native) | Tokens per call |
|---|---|---|---|---|
| qwen3.5-4b | 3 of 3 tasks | 2 of 3 | 8.4 | ~4,400 |
| qwen3.5-9b-mlx | 3 of 3 tasks | 2 of 3 | 15.1 | ~4,400 |

Each task was repeated three times, but at temperature 0 the repetitions produced identical output, so they are not independent samples. The honest count is three tasks per mode, not nine.

**Why JSON mode failed on "save a plan":** both models omitted the required `intent` field (the 4B model put intents inside the plan steps instead). Native tool calling passes the full schema, including the list of allowed intents, and both models then complied. This is a contract-communication failure, not a capability limit, and code validation caught every instance before anything ran.

**Context cost:** about 4,400 tokens per call, most of it tool definitions. This is the first input to the context budget work.

## Decision

- **Use native tool calling**, with code validation of every request. JSON mode stays as a tested fallback.
- **Develop the agent loop on qwen3.5-4b.** It matched the 9B model on these tasks at 1.8 times the speed, which halves iteration time.
- **Do not select the production model yet.** Single-step tool calls are too easy to separate the models; the triage project also found them close on accuracy (96% each) with similar evidence recall. The choice is made on the frozen development cases in the loop, where judgement (waiting, accepting, escalating) is tested, with Claude run once as a reference ceiling and cost comparison.

## What would change this decision

- The 4B model fails multi-step cases the 9B model passes: switch the default, and record the speed cost.
- Both fail the judgement cases: use a hosted model for planning and keep local models for extraction, or report that local inference does not meet the targets.
- Tool definitions crowd out case evidence in the context window: reduce the tools offered per step before changing the model.
