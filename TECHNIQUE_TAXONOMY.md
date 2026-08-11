# Relay technique taxonomy

Date: 2026-08-04

Status: systematic research dossier; no technique implementation is authorized
by this file. Conclusions are labelled `established`, `provisional`,
`contested`, or `unknown`.

## Decision boundary

Relay is a governed support agent. Its paid outcome is not fluent chat: it is a
correct support end state reached through the right tools, in a permitted
order, with bounded retries, visible approval for writes, and an auditable
receipt. General computer use, unconstrained research, coding agents, model
training, and autonomous multi-agent teams are outside this dossier.

The current baseline is already substantial. It has deterministic and
OpenAI-compatible planning, typed Pydantic tool schemas, read/write/risk
classes, planning budgets, server-side approval, per-action idempotency and
receipts, retry/dead-letter behavior, SQLite run history, generic outbound HTTP
controls, and an official-SDK MCP surface over stdio and authenticated
Streamable HTTP. The evidence gap is agent behavior across model, task horizon,
tool noise, repeated trials, failures, and adversarial tool content.

## Problem decomposition

| Layer | Independent decision | Serious families | Current Relay boundary |
| --- | --- | --- | --- |
| Intent and scope | identify goal, missing facts, policy and stop condition | deterministic classifier; model classification; clarify/refuse | bounded request and ticket state |
| Control policy | choose the next action or complete workflow | deterministic FSM/DAG; direct function calling; ReAct; plan-then-execute; bounded replanning; tree/search | deterministic plan or one model-produced typed plan |
| Tool discovery | expose only relevant capabilities | full registry; semantic/tool router; least-privilege allowlist; progressive skill loading | four registered internal tools plus five MCP tools |
| Argument construction | produce valid, policy-compatible calls | provider-native function calling; constrained schema; repair; deterministic normalization | strict Pydantic validation; no semantic tool benchmark |
| Scheduling | order dependencies and independent work | serial execution; parallel independent calls; dependency DAG | bounded serial action list |
| Working state | retain goal, observations and completed steps inside one run | full transcript; structured scratch state; summaries/checkpoints | persisted run/tool/attempt state, not model working memory |
| Durable memory | reuse facts or experience across runs | profile/semantic memory; episodic trajectories; procedural skills; no durable model memory | durable business records only |
| Feedback and verification | detect error and decide retry/replan/stop | deterministic predicates; tool feedback; critic/reflection; independent verifier; human review | deterministic validation, receipts, approval and failure classes |
| Multi-agent orchestration | split responsibility when separation adds value | single agent; planner/executor; planner/executor/verifier; specialist team/debate | no multi-agent layer |
| Side-effect governance | constrain real-world impact | pre-execution policy; risk-tier approval; capability/identity checks; compensation | read/write split and server-side approval |
| Security | resist malicious user/tool/memory content | data/instruction separation; task-alignment checks; dependency graph; least privilege; memory admission/repair | outbound trust controls and redaction; no injection benchmark |
| Reliability | survive partial failures without repeating successful work | per-action idempotency; bounded retry; checkpoint/resume; durable worker | SQLite single-process receipts and dead letters |
| Evaluation | determine success and operating envelope | syntax/tool-call score; trajectory predicates; exact end state; pass^k; fault and attack suites | local contract tests, no agent benchmark |

## Technique families and operating regions

### Deterministic workflow/state machine — `established`

Use an explicit graph or finite-state policy when the support procedure and
permitted transitions are known. It is the mandatory control because its
ordering, approval, and refusal behavior can be inspected without sampling.
The model may still classify intent or fill bounded fields. A framework is not
required for Relay's current short graph.

### Direct typed tool calling / ReAct — `established family`, `unknown Relay winner`

Direct function calling minimizes orchestration overhead for short tasks.
ReAct interleaves reasoning, action and environment observations, which can
recover when the next step depends on a tool result. BFCL tests call selection,
arguments, relevance, parallelism and multi-turn behavior, but does not prove
Relay policy compliance or end-state correctness. Direct/ReAct behavior must
therefore share Relay's server-side policy and receipt layer.

### Plan-then-execute and bounded replanning — `provisional`

Explicit plans help expose missing steps and dependencies on longer tasks.
PlanningArena and the 2026 Agent Planning Benchmark still find weaknesses in
executability, tool noise, broken tools and infeasible tasks. Replanning is
eligible only after a failed or state-changing observation and under a strict
step/token budget; it is not a reason to regenerate a successful workflow.

### Search/tree planning — `established niche`, `contested fit`

LATS and related search methods explore several trajectories and use feedback
or value estimates. They add calls, latency and evaluator dependence. Relay's
current support actions are short, costly to duplicate, and mostly specified
by policy, so tree search is excluded from the first experiment. It can be
retested only for reversible simulations with materially branching plans.

### Reflection and independent verification — `provisional`

Reflection can improve recovery when grounded in actual tool feedback, but
self-critique can repeat the same misconception. Deterministic state and policy
predicates remain primary. A model critic is eligible only for semantic choices
that cannot be exactly checked, and its utility, false rejection, latency and
cost must be measured separately.

### Working, episodic, semantic and procedural memory — `established distinctions`, `unknown fit`

Business state, current-run working state, user/profile facts, past
trajectories and reusable skills are different stores with different deletion
and authorization rules. Relay already persists business and execution state;
that is not permission to inject old conversations into a model. Recent work
shows error propagation, misaligned replay and memory poisoning. Durable memory
is admitted only for a named cross-run requirement, provenance, expiry,
authorization, admission checks and a no-memory control.

### Parallel independent calls — `established conditional`

Parallelism is valid only when calls have no data dependency, do not compete
for the same mutable resource, and preserve approval/receipt semantics. It is a
latency profile, not a different reasoning architecture. Parallel write calls
are excluded from the first experiment.

### Multi-agent teams — `contested default`

Role separation can provide an enforceable access boundary or independent
certification. It does not automatically improve reasoning. Controlled 2025
and 2026 comparisons report that multi-agent debate often fails to beat simple
single-agent baselines and teams can hurt when one agent already performs well.
Relay may add a separate verifier only when permissions or independent evidence
justify it; role-play alone is dominated by the single-agent control.

### Human approval and safe tool use — `established invariant`

Approval belongs at the side-effect boundary and displays validated tool
arguments. Tool filtering, risk tiers, identity/capability checks, step budgets,
and exact policy predicates constrain blast radius. Prompt-only safety is not a
replacement. AgentDojo, Task Shield and IPIGuard show useful risk reduction but
also require utility/false-refusal measurement; no defense is assumed perfect.

### Procedural skills — `provisional specialized memory`

Curated, versioned procedures can reduce repeated planning and token cost. A
skill is treated as governed software: typed inputs/outputs, provenance,
version, permissions, tests and rollback. Model-generated or community skills
do not enter Relay automatically. For four current tools and a short policy,
ordinary code remains the simpler control.

## Benchmark map

| Question | Public evidence | Limitation |
| --- | --- | --- |
| call and argument correctness | BFCL V4 | model/tool-call breadth, not Relay business state or approval |
| conversational policy and final state | tau-bench/tau2 and STATE-Bench | simulated users; domain policies differ; known scorer issues must be pinned |
| stateful dependencies and failure recovery | ToolSandbox | mobile-style tools and benchmark-specific state; API cost |
| planning diagnosis | PlanningArena and Agent Planning Benchmark | plan score is upstream evidence, not executed success |
| long-horizon general agency | AgentBench, GAIA, AgencyBench | poor task and cost fit for a bounded support product |
| indirect prompt injection | AgentDojo, Task Shield/IPIGuard results | utility and attack success depend on model, task and attack |
| memory/experience reuse | STATE-Bench and 2026 memory studies | cross-run memory is not required by every support task |
| production reliability | pass^k plus generated timeouts, 429/5xx, malformed/schema-drift and partial-state faults | public leaderboards cannot reproduce Relay's exact adapters and policies |
| realistic local acceptance | frozen Relay support scenarios | small and product-specific; must not become the only evidence |

Do not compare leaderboard headline numbers to local Relay results. Pin harness,
task subset, model/provider, prompt, tool schemas and scorer revision; keep
development and held-out tasks separate; repeat stochastic runs; report
category results and confidence intervals; inspect benchmark issues before use.

## Search protocol

- Search date: 2026-08-04.
- Sources: ACL Anthology, arXiv, OpenReview, official benchmark/project pages,
  GitHub repositories and live issue metadata.
- Main window: 2024-2026. Older work was retained only for family origins such
  as ReAct, Reflexion and LATS.
- Included: systematic surveys, controlled comparisons, benchmarks, negative
  results, official documentation and runnable maintained code.
- Excluded: popularity-only rankings, marketing feature tables, unrelated web/
  coding agents, unreleased code as an adoption target, and all license
  research or ranking.

### Reproducible query iterations

| Iteration | Query families | New decision-relevant family |
| ---: | --- | --- |
| 0 | `2025/2026 survey LLM agents planning memory tool use evaluation` | component taxonomy: policy, planning, tools, memory, verifier and orchestration |
| 1 | `BFCL V4 tau-bench ToolSandbox AgentDojo official` | state/end-state, pass^k, tool-failure and injection benchmark layers |
| 2 | `planning reflection simpler workflow negative results` | explicit contrary-evidence and multi-agent operating boundary |
| 3 | `ReAct Plan-and-Solve Reflexion LATS official` | reactive, plan-first, reflection and tree-search origins |
| 4 | `agent memory benchmark error propagation 2026` | separated business, working, episodic, semantic and procedural memory |
| 5 | official GitHub audit of eight frameworks and four benchmark harnesses | no new method family; maintenance and integration differences only |
| 6 | `web/tool prompt injection Task Shield IPIGuard memory poisoning` | memory admission/repair as part of the security boundary |
| 7 | `neuro-symbolic formal planner skills library world model` | procedural skill library; formal/symbolic planning maps to deterministic control |
| 8 | `support workflow approval rollback idempotency observability` | no new family; distributed reliability controls compose below the policy |
| 9 | `August 2026 recent agent orchestration taxonomy and contrary evidence` | no new family; added newer benchmarks and limitations only |

Iterations 8 and 9 are consecutive expansions with no new decision-relevant
family after the procedural-skill family was added. Taxonomy saturation is
`PASS` for this dated scope, not a timeless completeness claim.

## Primary survey and benchmark anchors

- [Agent evaluation survey, Findings ACL 2026](https://aclanthology.org/2026.findings-acl.1330/)
- [Agent paradigms review, COLING 2025](https://aclanthology.org/2025.coling-main.652/)
- [PlanGenLLMs, ACL 2025](https://aclanthology.org/2025.acl-long.958/)
- [PlanningArena, ACL 2025](https://aclanthology.org/2025.acl-long.1499/)
- [BFCL V4](https://gorilla.cs.berkeley.edu/leaderboard)
- [tau-bench](https://arxiv.org/abs/2406.12045)
- [ToolSandbox](https://arxiv.org/abs/2408.04682)
- [AgentDojo](https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html)
- [Task Shield, ACL 2025](https://aclanthology.org/2025.acl-long.1435/)
- [Memory-management effects, ACL 2026](https://aclanthology.org/2026.acl-long.27/)
- [Do more agents help?](https://arxiv.org/abs/2606.05670)

