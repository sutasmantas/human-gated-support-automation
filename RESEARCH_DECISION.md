# Relay research decision

Date: 2026-08-04

## Outcome

Relay's systematic evidence gate is `PASS`. Its experiment and overall
technique-ceiling gates remain `PARTIAL`: this slice designed but did not run
R0-R3.

The governed runtime remains the product core. The strongest next comparison
is not a framework rewrite or a multi-agent demo. It is a matched evaluation of
deterministic control, direct typed calling, plan-first execution and
state-grounded bounded replanning through the same Relay tools, policy, state
and scorer.

## Retained families

| Family | Decision | Operating region |
| --- | --- | --- |
| deterministic workflow/state predicates | core | known procedures, high-risk actions and exact policy checks |
| direct typed tool calling/ReAct | first experiment | short and medium tasks whose next step depends on observations |
| plan-then-execute | experiment | dependency-heavy longer tasks; must beat direct control |
| bounded replanning | first experiment | failure, changed-state and infeasible-plan recovery only |
| parallel calls | later specialized profile | independent reads with measured latency gain |
| deterministic verifier plus human approval | core invariant | every profile; writes/high-risk actions |
| task-alignment/least-privilege defenses | security experiment | untrusted user or tool content |
| structured/episodic/procedural memory | deferred | only a named cross-session client requirement |
| tree search | deferred niche | reversible high-branch simulations, not ordinary support writes |
| multi-agent roles | conditional only | enforceable access separation or independent certification |

## Rejected duplicates and premature adoption

- No AutoGen or CrewAI rewrite: multi-agent behavior has no established Relay
  operating region and adds a second orchestration/policy surface.
- No simultaneous LangGraph, Pydantic AI and OpenAI Agents SDK adoption. Use
  current interfaces; add one thin optional adapter only when an experiment or
  durability requirement cannot be expressed cleanly.
- No custom benchmark loader before trying to reuse BFCL, tau/STATE,
  ToolSandbox and AgentDojo code/data contracts.
- No new retry, approval, receipt, outbound-security or MCP layer; those are
  already tested Relay components.
- No model-generated skill or memory store without lifecycle, permission,
  poisoning and deletion acceptance.

## External answers versus unresolved questions

| Question | Evidence reuse | Status |
| --- | --- | --- |
| approval/policy location | external evidence plus local proof | closed: server-side side-effect boundary |
| one run versus repeated reliability | public benchmark consensus | closed: repeated pass^k/category evidence required |
| default multi-agent architecture | controlled comparisons | closed: no |
| default durable model memory | contrary memory evidence | closed: no |
| best Relay control policy by task horizon | public evidence does not match exact tools/policy | unresolved; R1 |
| best utility/security defense tradeoff | model/task/attack dependent | unresolved; R2 |
| cross-session memory value | no current product requirement | deliberately deferred; R3 only when triggered |

## Exact next controlled work

1. R0: adapt pinned benchmark subsets to one Relay case/trajectory/final-state
   schema and prove scorer agreement/mutation sensitivity.
2. R1: run deterministic, direct, plan-first and bounded-replan profiles on the
   frozen 72/72 grouped corpus with two selectable models and repeated trials.
3. R2 only after R1: test least privilege and task/action alignment against
   benign and AgentDojo-derived adversarial cases.
4. R3 only after a real cross-session requirement exists.

No step above was started in this dossier slice.

## Eleven systematic evidence gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Problem decomposition | PASS | independent layers and families in `TECHNIQUE_TAXONOMY.md` |
| Search protocol | PASS | dated sources, window, rules and ten iterations recorded |
| Survey coverage | PASS | 2025 paradigm/planning reviews and 2026 agent-evaluation survey anchor the taxonomy |
| Benchmark coverage | PASS | BFCL, tau/STATE, ToolSandbox, AgentDojo, planning and memory limits mapped |
| Existing-answer search | PASS | externally closed questions separated from R0-R3 |
| Technique-family saturation | PASS | iterations 8 and 9 added no family |
| Candidate comparison | PASS | `EVIDENCE_MATRIX.csv` includes quality, cost, health, failures and fit |
| Contrary evidence | PASS | multi-agent, memory, reflection, benchmark/scorer and simple-control limits recorded |
| Implementation evidence | PASS | maintained repositories, exact pins, issues and seams in `GITHUB_IMPLEMENTATION_AUDIT.md` |
| Portfolio fit | PASS | profiles add governed agent evaluation; duplicates/framework rewrites rejected |
| Review status | PASS | every conclusion/candidate uses established/provisional/contested/unknown status |

## Claim boundary

Defensible now: Relay has a systematic, pinned architecture and benchmark plan
for governed tool agents, and its existing implementation proves typed tools,
approval, receipts, bounded retries and MCP proposal-only writes.

Not defensible now: Relay beats any model/framework, has passed BFCL/tau-bench/
AgentDojo, supports safe persistent memory, is multi-agent, prevents all prompt
injection, or provides distributed exactly-once/durable production execution.

