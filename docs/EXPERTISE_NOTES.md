# Relay expertise notes

**Verification:** [claim-to-artifact map and rerun commands](https://sutasmantas.github.io/evidence/#relay) · [machine-readable receipt](https://sutasmantas.github.io/evidence/receipt.json)

Date: 2026-08-04

These notes translate the technique dossier into scoped delivery decisions.
No local model comparison was run; external conclusions and unresolved local
questions are identified explicitly.

## Evaluate workflow success from state transitions, not final prose

### Client trigger

- Job wording or deliverable: support agent, tool-calling workflow, ticket/CRM
  automation, policy-following assistant, or agent evaluation.
- Measured proposal frequency: not quantified for this slice.
- Existing reusable project: Relay's typed tools, SQLite attempts/receipts and
  approval/audit events.

### Failure symptom or unanswered choice

An agent can produce a convincing completion message after skipping a required
step, calling the wrong tool, violating policy or leaving partial external
state. Text similarity cannot distinguish those outcomes.

### Competing options

| Option | Why plausible | Main failure risk |
| --- | --- | --- |
| grade final answer | cheap and familiar | rewards plausible prose despite wrong state |
| exact final-state score | matches business outcome | can miss forbidden intermediate actions |
| trajectory predicates plus final state | checks both outcome and path | requires executable task-specific assertions |

### Controlled comparison

- Evidence-reuse level: established external benchmark answer plus portfolio
  implementation evidence.
- Sources: tau-bench uses goal database state and pass^k; BFCL diagnoses tool
  calls; AgentDojo separates utility and attack success. Relay already persists
  tool calls, attempts, receipts and events.
- Contrary evidence/limits: one final state can have several valid paths, so
  the scorer must require only policy-critical transitions and permit valid
  alternatives. Public domains do not reproduce Relay policies.
- Representative cases/metrics/budget: frozen in R0/R1 of
  `BENCHMARK_DESIGN.md`; no local result exists.
- Outside comparison: subjective conversational style.

### Result

External evidence closes the evaluation architecture: exact state and
policy-critical trajectory checks precede semantic answer quality. The best
Relay planning profile remains unresolved until R1.

### Decision rule

Define the required end state, forbidden effects and mandatory policy steps
before selecting a model or framework. Accept multiple safe trajectories; fail
any run that reaches a polished answer through a prohibited action.

### Delivery control

Ship an executable acceptance report containing start state, tool/event trace,
final-state predicates, policy violations, retries/receipts, latency and cost.

### Reuse boundary

- Reusable: Relay event/receipt types, exact-state scorer design and pass^k
  protocol.
- Client-specific: authoritative state, allowed alternative paths, policies,
  failure cost and semantic quality rubric.
- Unsupported: Relay has already passed a public agent benchmark or production
  workflow evaluation.

### Proposal-safe insight

I evaluate tool agents against the state they actually changed and the policy
steps they followed, not just the final message. That catches silent partial
completion and unsafe shortcuts before a workflow is promoted.

### Evidence

- Code: `support_desk/store.py`, `support_desk/tools.py`.
- Tests: `tests/test_agent_tools.py`, `tests/test_outbound_adapter.py`.
- Research/design: `TECHNIQUE_TAXONOMY.md`, `BENCHMARK_DESIGN.md`.
- Reproduction: current test commands in `docs/EXECUTION_CHECKPOINT.md`; R0/R1
  have no result command yet.

### Interview follow-up

- Likely question: Why is exact final state not enough?
- Short answer: it misses forbidden intermediate calls, duplicate writes and
  approval bypass; trajectory predicates catch those without requiring one
  exact valid path.
- Deeper evidence: tau-bench scoring boundary and R0 mutation checks.

### Central index disposition

- Added card: yes.
- Card heading: **Grade agent workflows on state and policy, not prose**.

## Choose the simplest control policy that meets the task horizon

### Client trigger

- Deliverable: choosing between a deterministic workflow, tool-calling agent,
  planner/executor graph or multi-agent system.
- Measured proposal frequency: not quantified.
- Reusable project: Relay's deterministic and OpenAI-compatible planners behind
  one tool/policy contract.

### Failure symptom or unanswered choice

Agent-framework complexity is often selected before anyone shows that the task
needs long-horizon planning, backtracking, memory or role separation.

### Competing options

| Option | Why plausible | Main failure risk |
| --- | --- | --- |
| deterministic FSM/DAG | exact, cheap, auditable | rigid on novel tasks |
| direct/ReAct tool calling | adapts after observations | loops/tool mistakes |
| plan-first or bounded replan | exposes dependencies and recovers | stale plans and added calls |
| tree/multi-agent search | more exploration/specialization | correlated errors, coordination and cost |

### Controlled comparison

- Evidence-reuse level: triangulated external answer; Relay winner unresolved.
- Sources: agent/planning surveys, BFCL/tau-style benchmarks, ReAct, LATS, and
  controlled multi-agent comparisons.
- Contrary evidence: multi-agent debate often fails to beat simple baselines;
  verifier/team ablations can hurt when a single agent is already strong.
- Local cases/metrics: R1 freezes short/medium/long tasks, exact state, pass^k,
  safety, steps, latency and cost.
- Outside comparison: open-ended research, computer use and coding agents.

### Result

External evidence closes the default: do not begin with multi-agent or search.
It does not identify whether direct or bounded-replan control wins each Relay
task stratum.

### Decision rule

Use deterministic control for known/high-risk procedures. Test direct calling
for short adaptive work and bounded replanning for longer or failed-state work.
Add roles only for enforced permissions or independently valuable evidence.

### Delivery control

Require a matched task-horizon/cost/safety matrix before promoting a more
complex controller; keep the deterministic route selectable.

### Reuse boundary

- Reusable: profile interfaces, task-horizon labels, common tool/policy layer.
- Client-specific: workflow entropy, branch count, failure recovery, latency,
  cost and required separation of duties.
- Unsupported: a named framework or multi-agent architecture is universally
  more production-ready.

### Proposal-safe insight

I start agent work with the shortest control loop that can meet the workflow,
then add planning or role separation only where representative cases show a
recovery or governance benefit worth the latency and cost.

### Evidence

- Code: `support_desk/engine.py`, `support_desk/tools.py`.
- Research: `EVIDENCE_MATRIX.csv`, `GITHUB_IMPLEMENTATION_AUDIT.md`.
- Future comparison: R1 in `BENCHMARK_DESIGN.md`.

### Interview follow-up

- Likely question: When would you choose LangGraph or multiple agents?
- Short answer: when durable branching/resume or enforced role separation is a
  real requirement and a thin adapter passes the current tool/policy contract.
- Deeper evidence: framework audit and R1 routing thresholds.

### Central index disposition

- Added card: yes.
- Card heading: **Choose agent complexity from task horizon and governance**.

## Keep business state separate from model memory

### Client trigger

- Deliverable: persistent assistant memory, customer preferences, prior-ticket
  learning, session resume or reusable agent skills.
- Measured proposal frequency: not quantified.
- Reusable project: Relay's authoritative SQLite ticket, action, receipt and
  event state.

### Failure symptom or unanswered choice

Calling every persisted object “memory” can cause stale conversation text or a
poisoned past trajectory to override authoritative current business state.

### Competing options

| Option | Why plausible | Main failure risk |
| --- | --- | --- |
| full transcript | simplest context continuity | token growth, stale instructions, leakage |
| structured authoritative state | exact and permissionable | narrower than conversational recall |
| episodic/semantic retrieval | cross-run reuse | error propagation and misaligned replay |
| curated procedural skills | reusable workflow knowledge | supply-chain, staleness and permissions |

### Controlled comparison

- Evidence-reuse level: triangulated external answer for separation; local
  memory value remains untested.
- Sources: 2026 ACL memory-management study, STATE-Bench, memory poisoning and
  skill-lifecycle research.
- Contrary evidence: similar old experiences can reproduce wrong outputs;
  successful trajectories can still be misleading; no memory strategy
  dominates all models/tasks.
- Future test: R3 only after a named client requirement.

### Result

The stores must remain separate. Relay's durable execution/business records do
not constitute a general model memory claim.

### Decision rule

Read current authoritative state first. Add only the minimum named memory type,
with provenance, authorization, expiry/deletion, quality admission and a
no-memory control.

### Delivery control

Acceptance includes stale/contradictory facts, cross-tenant access, malicious
memory writes, deletion and selective repair—not just recall accuracy.

### Reuse boundary

- Reusable: state/memory taxonomy, version/provenance fields and test shapes.
- Client-specific: retention, authority, privacy, personalization and deletion.
- Unsupported: Relay learns safely across customers or sessions today.

### Proposal-safe insight

I keep authoritative workflow state separate from optional model memory, so an
old conversation or learned example cannot silently override the current
record. Persistent memory is added only with provenance, expiry and adversarial
acceptance cases.

### Evidence

- Code: `support_desk/store.py`.
- Research: memory rows in `TECHNIQUE_TAXONOMY.md` and
  `EVIDENCE_MATRIX.csv`.
- Future design: R3 in `BENCHMARK_DESIGN.md`.

### Interview follow-up

- Likely question: Isn't the SQLite history already agent memory?
- Short answer: it is authoritative execution evidence; whether any of it may
  be retrieved into a future model context is a separate policy and benchmark.
- Deeper evidence: memory-management contrary evidence and R3 gates.

### Central index disposition

- Added card: no.
- Reason: too narrow for current job retrieval until a cross-session memory
  comparison exists; the local note preserves the scoping boundary.

## Treat tool output as untrusted data

### Client trigger

- Deliverable: agent reads tickets, email, documents, websites or third-party
  API text before taking actions.
- Reusable project: Relay's risk classes, tool allowlist, approval and outbound
  controls.

### Failure symptom or unanswered choice

External text can contain instructions that redirect the agent, exfiltrate
data or launder a dangerous write through an innocent-looking summary.

### Competing options

| Option | Why plausible | Main failure risk |
| --- | --- | --- |
| delimit/prompt only | cheap | model may still follow injected instructions |
| sanitize content | removes scripts/markup | semantic malicious text survives |
| least privilege plus task/action checks | constrains executable behavior | false refusals and policy maintenance |
| human approval | catches risky effects | fatigue and misleading descriptions |

### Controlled comparison

- Evidence-reuse level: established threat, provisional defense winner.
- Sources: AgentDojo, Task Shield and IPIGuard.
- Contrary evidence: attacks and defenses vary by model/task; utility can fall;
  benchmark scorer defects can misclassify blocked attempted calls.
- Local design: R2 measures exact effects, ASR, benign utility and false
  refusal. No local security result exists.

### Result

The untrusted-data boundary and least-privilege requirement are established.
No specific prompt-injection defense is promoted before R2.

### Decision rule

Separate data from instructions, expose the minimum tools, enforce exact
server-side policy, and approve raw validated write arguments. Add semantic
defenses only when their utility/security tradeoff passes matched cases.

### Delivery control

Use benign and adversarial executable cases and assert attempted versus
executed effects separately; hard fail on any unauthorized executed effect.

### Reuse boundary

- Reusable: attack categories, exact-effect assertions, risk/approval layer.
- Client-specific: trusted sources, tools, identities, policies and acceptable
  false refusal.
- Unsupported: sanitization or a prompt makes Relay injection-proof.

### Proposal-safe insight

I treat text returned by tools as untrusted data and keep permissions and
approval outside the model. Security testing measures both blocked effects and
the legitimate workflows a defense mistakenly refuses.

### Evidence

- Code: `support_desk/tools.py`, `support_desk/outbound.py`.
- Tests: `tests/test_agent_tools.py`, `tests/test_outbound_adapter.py`.
- Research/design: R2 in `BENCHMARK_DESIGN.md`.

### Interview follow-up

- Likely question: Why isn't HTML or text sanitization enough?
- Short answer: it removes unsafe syntax, not a valid sentence telling the
  model to misuse an allowed tool; permission and task-alignment checks bound
  the action.
- Deeper evidence: AgentDojo and R2 exact-effect design.

### Central index disposition

- Added card: no.
- Reason: this decision is indexed once by the joint Website Assistant dossier
  under **Treat external content as data, not authority** to avoid duplicate
  buyer retrieval paths.

