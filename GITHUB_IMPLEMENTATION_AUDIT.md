# Relay GitHub implementation audit

Date: 2026-08-04

Purpose: find maintained code before writing substantial custom agent logic.
Popularity is not an
adoption criterion. Pins are inspection anchors, not dependency upgrades.

## Existing implementation seam

Relay already owns the hard product-specific boundary in `support_desk/tools.py`,
`support_desk/store.py`, `support_desk/outbound.py`, and
`support_desk/mcp_server.py`: typed calls, risk classes, approval, attempts,
receipts, retry/dead-letter, outbound trust policy and MCP proposal mapping.
Replacing that with a monolithic agent framework would discard tested behavior
and create migration risk. Reuse should therefore target planners, benchmark
loaders/scorers, tracing adapters or durable orchestration components behind
the existing contracts.

## Runtime/framework comparison

| Repository and inspected pin | Health on 2026-08-04 | Useful component | Current defects inspected | Relay decision |
| --- | --- | --- | --- | --- |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) `19e364c` | active same day; 60 open issues | compact model/tool loop, tracing, sessions, handoffs | #4150 branch merge, #4070 missing generic error span, #4069 duplicate session input | reference/adapt the loop or tracing seam only if provider-specific experiments need it; do not replace Relay policy/store |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) `b2926a0` | active; 672 open issues | explicit state graph, checkpoint/interrupt, human-in-loop and durable adapters | #8522 strict msgpack default after security advisory; #8517 ignored max concurrency | strongest future candidate when Relay requires branching durable resume; integrate behind typed tool/policy boundary after narrow compatibility test |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) `c8bcbb1` | active same day; 616 open issues | typed model/tool/result contracts and usage limits | #7139 context-window fallback; #7133 incomplete cost-limit coverage | useful reference, but duplicates existing Pydantic validation and provider seam; no adoption for first experiment |
| [microsoft/semantic-kernel](https://github.com/microsoft/semantic-kernel) `383d102` | active; 253 open issues | plugin/tool orchestration, process/workflow patterns | #14246 blocks MCP 2.x; provider-specific embedding defect #14265 | do not add beside current Python/MCP runtime; reference workflow patterns only |
| [microsoft/autogen](https://github.com/microsoft/autogen) `027ecf0` | last repository push 2026-04; 972 open issues | event-driven multi-agent messaging and workbench | #8014 MCP 2.0 break; #8008 approval gate still proposed | reject for current slice: no measured multi-agent need, MCP/version and approval integration burden |
| [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) `7accafb` | active same day; 764 open issues | declarative role/task crews | #6813 model routing drift; #6798 unsafe pickle/import report | reject role-based rewrite; role prompts do not create an enforceable security boundary |
| [huggingface/smolagents](https://github.com/huggingface/smolagents) `e3a5b89` | active in July; 743 open issues | small readable tool/code agent loop | #2586 retry defaults disable backoff; #2593 misleading auth error | reference for minimal loop only; code-agent surface is outside Relay and retry semantics conflict with current controls |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) `a4f4ccd` | active; 507 open issues | official MCP stdio/Streamable HTTP protocol implementation | #3250 OAuth refresh state, #3240 wrong refresh endpoint, #3244 Windows encoding | retain existing official SDK integration; pin and test current transports; do not claim OAuth or broad client compatibility |

## Benchmark implementation comparison

| Repository and inspected pin | What to reuse | Defect/version caveat | Decision |
| --- | --- | --- | --- |
| [ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla) `6ea5797` | BFCL V4 schemas, categories and scorers for call/tool relevance/parallel/multi-turn tests | #1352 asks how synthetic request failures are configured; freeze category and handler | adapt a bounded diagnostic subset; never compare its headline score directly to local Relay results |
| [sierra-research/tau-bench](https://github.com/sierra-research/tau-bench) `59a200c` | simulated user, policy tasks, exact database end-state and pass^k | domain-gap issues #83/#84; project name/version must be pinned | adapt retail/support-shaped tasks and scorer ideas to Relay state |
| [apple/ToolSandbox](https://github.com/apple/ToolSandbox) `165848b` | stateful tool dependency, failure and conversational milestones | issue #6 records API-cost concern; mobile domain differs | copy/refit selected state/fault scenarios, not the full mobile environment |
| [ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo) `089ed46` | executable benign/adversarial cases and utility/attack-success scoring | #168 reports blocked attempted calls can be scored as success | use only after pinning/resolving scorer semantics and add Relay exact-side-effect assertions |
| [microsoft/STATE-Bench](https://github.com/microsoft/STATE-Bench) `4efcbf2` | enterprise support tasks, deterministic assertions and memory/no-memory interface | #36 reports sibling record identity can yield false zero completion | reserve for the later memory question; freeze corrected scorer before any result |

## Component-level reuse map

| Needed capability | Reuse before custom logic | Relay-owned adapter |
| --- | --- | --- |
| public tool-call cases | BFCL loaders/categories/scorers | translate BFCL tool definitions and expected calls to `ToolCall` without bypassing `ToolRegistry` |
| exact conversational end state | tau-bench/STATE-Bench task and state predicates | seed Relay SQLite and compare final ticket/action/receipt state |
| tool failure/state dependency | ToolSandbox scenario patterns | drive existing normalized failures and attempts, not a second retry engine |
| injection evaluation | AgentDojo cases/utility-ASR split | expose untrusted tool text to planner while exact Relay policy guards writes |
| model/tool loop | current OpenAI-compatible planner first; OpenAI Agents SDK as optional reference | implement a thin `Planner` adapter only if a comparison needs provider-native behavior |
| graph/durable resume | LangGraph only after a long-running use case exists | nodes call current registry/store; checkpoint must not replace receipts |
| MCP | official Python SDK already adopted | keep proposal-only write mapping and transport/auth tests |

## Explicit non-adoptions

- Do not introduce AutoGen or CrewAI merely to claim multi-agent work. Current
  evidence does not show a Relay operating region that beats a single governed
  controller.
- Do not install several agent frameworks for one benchmark. The comparable
  object is the control policy behind one Relay tool and state contract.
- Do not copy retry, approval, receipt, SSRF or MCP transport logic from a
  framework. Relay already has focused tested versions.
- Do not ingest model-generated/community skills. A future skill must be a
  versioned, permissioned, testable procedure with provenance and rollback.
- DOM/content sanitizers are not agent prompt-injection defenses; semantic
  instruction attacks need executable utility and attack tests.

## Minimal integration checks before any future adoption

1. One successful read-only case reaches the same `ToolCall`, event and final
   state as the deterministic control.
2. One invalid/missing-tool case fails without a write.
3. One state-changing proposal remains at zero effects before approval and one
   receipt after approval.
4. A timeout after one completed action retries only the incomplete action.
5. Trace usage, tool arguments, policy decision and final state remain
   exportable to the shared evaluation adapter.
6. The optional dependency can be disabled without altering the deterministic
   profile.

