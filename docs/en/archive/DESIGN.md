# Multi-Agent Autonomous Development System - Design

## 1. System Architecture

The system is organized around an agent runtime. Agents are replaceable workers. The runtime is the stable control plane.

```text
User Goal
  -> Goal Intake
  -> Agent Runtime
       -> Context Manager
       -> Task Board
       -> Tool Registry
       -> Command Registry
       -> Permission Manager
       -> Decision Manager
       -> Workspace Manager
       -> Eval Runner
       -> Memory Store
       -> Event Log
       -> Budget Controller
       -> Recovery Engine
  -> Specialized Agents
       -> Planner
       -> Architect
       -> Research
       -> Coder
       -> UI/Experience
       -> Tester
       -> Reviewer
       -> AutoCorrection
       -> Memory
       -> Release
  -> Artifacts
       -> Code
       -> Reports
       -> UI
       -> Tests
       -> Experiment Logs
       -> Final Summary
```

### 1.1 Runtime Component Architecture

The runtime is composed of several cooperating control-plane modules.

```text
CLI / Local UI
  -> Command Router
       -> /init
       -> /plan
       -> /brainstorm
       -> /research
       -> /compact
       -> /decide
       -> /review
       -> /debug
       -> /handoff
  -> Orchestrator
       -> State Machine
       -> Task Scheduler
       -> Decision Manager
       -> Budget Controller
  -> Context Layer
       -> Root Guidance Loader
       -> Context Retriever
       -> Context Compressor
       -> Handoff Builder
  -> Agent Layer
       -> PlannerAgent
       -> ResearchAgent
       -> CoderAgent
       -> UIExperienceAgent
       -> TesterAgent
       -> ReviewerAgent
       -> AutoCorrectionAgent
  -> Tool Layer
       -> File Tools
       -> Search Tools
       -> Patch Tools
       -> Shell/Test Tools
       -> Browser/Screenshot Tools
       -> Research Tools
       -> Memory Tools
  -> Persistence Layer
       -> AGENTS.md
       -> .agent/project.json
       -> .agent/policies.json
       -> .agent/context/
       -> .agent/tasks/
       -> .agent/runs/
       -> .agent/memory/
       -> Git / Worktrees
```

The Orchestrator should not contain all intelligence itself. It coordinates state, permissions, tasks, budgets, and artifact flow. Specialized agents provide judgment and generation under runtime control.

### 1.2 Core Data Flow

```text
User goal or command
  -> Command Router
  -> Root guidance and memory retrieval
  -> Orchestrator state transition
  -> Agent prompt assembly
  -> Tool calls and artifact creation
  -> Verification and review
  -> Keep/discard decision
  -> Context snapshot and memory update
  -> User report or next decision point
```

For long tasks, the data flow repeats across many iterations. The stable artifacts, not the transient chat history, are the source of continuity.

### 1.3 Architectural Layers

The system should keep these layers separate:

- Interface layer: CLI, local UI, and future dashboard.
- Command layer: reusable workflows such as `/init`, `/brainstorm`, and `/compact`.
- Orchestration layer: state machine, task scheduling, decision escalation, and budget control.
- Agent layer: role-specific model workers.
- Tool layer: structured capabilities exposed to agents.
- Evaluation layer: tests, builds, reviews, benchmarks, screenshot checks, and trajectory evals.
- Persistence layer: root guidance, project metadata, event logs, tasks, memory, context snapshots, and Git state.

This separation keeps the system extensible. New agents, tools, commands, and UI surfaces should plug into the runtime without rewriting the whole control plane.

## 2. Main Runtime Loop

```text
1. Receive user goal.
2. Generate GoalSpec.
3. Build initial task plan.
4. Select output strategy.
5. Detect major decision points and ask the user when configured policy requires it.
6. Compact context when threshold, phase boundary, or handoff policy requires it.
7. Prepare workspace.
8. Assign ready tasks.
9. Agent performs work with allowed tools.
10. Runtime records artifacts and events.
11. Run verification.
12. If verification passes, review and keep.
13. If verification fails, trigger auto-correction.
14. If correction fails, rollback or mark blocked.
15. Update memory.
16. Continue until done, budget exhausted, or blocked.
17. Generate final report.
```

## 3. Core Concepts

### 3.1 GoalSpec

The structured representation of the user's goal.

Example:

```json
{
  "goal": "Build a local markdown knowledge-base system",
  "constraints": ["local-first", "markdown import", "semantic search"],
  "target_outputs": ["web_app", "readme", "tests"],
  "definition_of_done": [
    "Can import markdown folder",
    "Can create searchable index",
    "Can ask questions with citations",
    "Can run locally"
  ],
  "verification": ["unit_tests", "smoke_test", "ui_screenshot"]
}
```

### 3.2 Task

The smallest schedulable unit of work.

```json
{
  "id": "T-001",
  "title": "Implement markdown importer",
  "role": "CoderAgent",
  "status": "ready",
  "dependencies": [],
  "acceptance": [
    "Recursively scans .md files",
    "Extracts title, path, and body",
    "Has unit tests"
  ],
  "artifacts": ["src/importer.ts", "tests/importer.test.ts"]
}
```

### 3.3 Experiment

A controlled attempt to improve the system.

```json
{
  "id": "EXP-042",
  "idea": "Add hybrid retrieval",
  "baseline": "vector search only",
  "candidate": "BM25 plus vector search plus rerank",
  "evaluator": "eval/search_quality.json",
  "metrics_before": {"hit_rate": 0.62},
  "metrics_after": {"hit_rate": 0.71},
  "decision": "keep"
}
```

### 3.4 Artifact

Any durable output:

- Source code.
- Patch.
- Test.
- Report.
- PDF.
- Screenshot.
- Research note.
- Eval result.
- Memory entry.

### 3.5 DecisionPoint

A major branch point where user intent materially affects the result.

```json
{
  "id": "D-003",
  "question": "Which output form should this tool prioritize?",
  "recommended": "local_web_app",
  "options": [
    {
      "id": "local_web_app",
      "label": "Local web app",
      "tradeoff": "Best for repeated interactive use, costs more frontend work"
    },
    {
      "id": "cli",
      "label": "CLI",
      "tradeoff": "Fast to build and automate, less friendly for non-technical use"
    },
    {
      "id": "pdf_report",
      "label": "PDF report",
      "tradeoff": "Best for sharing results, not suitable for ongoing operation"
    }
  ],
  "default": "local_web_app",
  "granularity_required": "balanced",
  "impact": {
    "scope": "medium",
    "budget": "medium",
    "risk": "low",
    "quality": "high"
  }
}
```

The Decision Manager decides whether to ask the user, auto-select the recommended option, or defer the decision based on configured granularity.

### 3.6 ContextSnapshot

A compact, machine-readable summary that lets the same or another agent continue long-running work without carrying full conversation history.

```json
{
  "goal": "Build a password testing tool",
  "definition_of_done": ["usable local UI", "strength scoring", "clear privacy behavior"],
  "accepted_decisions": ["local-first", "no online breach API by default"],
  "active_tasks": ["T-004", "T-007"],
  "modified_files": [
    {"path": "src/scoring.ts", "reason": "added entropy and policy scoring"}
  ],
  "verification": [
    {"command": "npm test", "result": "passed"}
  ],
  "failures": [
    {"summary": "UI overflow on mobile", "status": "fixed"}
  ],
  "research_claims": [
    "Password tools should distinguish strength estimation from actual compromise detection"
  ],
  "next_actions": ["add generator tests", "run UI screenshot check"]
}
```

Context snapshots are produced by `/compact`, phase transitions, handoffs, and automatic context budget policies.

### 3.7 Command

A named reusable workflow.

```json
{
  "name": "brainstorm",
  "description": "Generate and rank product or implementation ideas",
  "arguments": ["topic", "constraints"],
  "allowed_tools": ["read_memory", "query_web", "create_task", "create_decision"],
  "expected_artifacts": ["brainstorm_report.md", "candidate_tasks.json"]
}
```

Commands can be user-invoked or agent-invoked when policy allows it.

## 4. Agent Roles

### 4.1 GoalSpecAgent

Converts user input into a structured goal.

Outputs:

- `goal_spec.json`
- assumptions
- open questions if necessary

### 4.2 PlannerAgent

Creates milestones and tasks.

Outputs:

- `task_plan.json`
- dependency graph
- first iteration plan

### 4.3 ArchitectAgent

Chooses implementation architecture.

Outputs:

- tech stack
- module boundaries
- data flow
- constraints

### 4.4 ResearchAgent

Turns external knowledge into executable hypotheses.

Sub-roles may include:

- ResearchScout
- PaperReader
- IdeaSynth
- ExperimentDesigner
- CitationTracker

Outputs:

- research notes
- claims
- evidence
- implementation ideas
- experiment plans

### 4.5 CoderAgent

Implements scoped tasks in isolated workspaces.

Outputs:

- code patches
- tests
- implementation notes

### 4.6 UIExperienceAgent

Decides and implements suitable output experiences.

It should not blindly create a web page. It chooses the best medium:

- Web app.
- CLI.
- TUI.
- Desktop app.
- PDF report.
- Markdown knowledge base.
- Dashboard.
- API service.

Outputs:

- output medium recommendation
- interaction model
- screens or report structure
- UI implementation tasks
- visual acceptance criteria

### 4.7 TesterAgent

Creates and runs validation.

Outputs:

- test plan
- test files
- test results
- reproduction steps

### 4.8 ReviewerAgent

Reviews patches before keeping or merging.

Outputs:

- review findings
- risk assessment
- merge recommendation

### 4.9 AutoCorrectionAgent

Handles failures and repair loops.

Outputs:

- failure summary
- root-cause hypotheses
- repair patch
- retry decision

### 4.10 MemoryAgent

Stores useful knowledge.

Outputs:

- project memory
- user preference memory
- experiment lessons
- reusable patterns

### 4.11 ReleaseAgent

Packages final output.

Outputs:

- README
- run instructions
- release notes
- final report

## 5. State Machine

Each run moves through controlled states.

```text
INIT
  -> SPEC
  -> PLAN
  -> BRAINSTORM optional
  -> DECIDE optional
  -> RESEARCH optional
  -> DESIGN
  -> IMPLEMENT
  -> VERIFY
  -> REVIEW
  -> REPAIR optional
  -> KEEP_OR_DISCARD
  -> MEMORY_UPDATE
  -> REPORT
  -> DONE
```

Allowed transitions:

- `VERIFY -> REPAIR` when checks fail.
- `REPAIR -> VERIFY` after patch.
- `PLAN -> DECIDE` or `DESIGN -> DECIDE` when a major branch decision is detected.
- `DECIDE -> PLAN`, `DECIDE -> DESIGN`, or `DECIDE -> IMPLEMENT` after user choice or default selection.
- `PLAN -> BRAINSTORM` when the goal is broad, creative, or has multiple viable directions.
- `BRAINSTORM -> DECIDE` when top candidates require user steering.
- `BRAINSTORM -> PLAN` when the system can safely select a direction.
- `KEEP_OR_DISCARD -> IMPLEMENT` when more tasks remain.
- `KEEP_OR_DISCARD -> REPORT` when done.
- Any state can transition to `BLOCKED` when budget or safety rules stop progress.

## 6. Decision Management

The Decision Manager prevents two bad extremes:

- The system blindly makes major product or architecture choices without the user's intent.
- The system interrupts the user for every small implementation detail.

Decision granularity is configurable:

```text
autopilot: ask only for safety-critical or irreversible decisions
balanced: ask for major product, architecture, budget, or privacy decisions
collaborative: ask for more frequent product and UX choices
manual: ask before significant changes or scope expansion
```

Decision detection signals:

- Multiple viable product directions with different user outcomes.
- Large scope expansion from the original goal.
- Significant budget or time increase.
- Privacy, security, or data-sensitivity implications.
- Irreversible filesystem, deployment, or external-service actions.
- Technology choice that strongly affects maintenance or user experience.
- Research results reveal competing implementation strategies.

Decision request format:

```json
{
  "question": "Should the password testing tool include breach-list checking?",
  "recommended": "local_optional_import",
  "options": [
    {
      "id": "no_breach_check",
      "label": "No breach check",
      "tradeoff": "Simpler and fully local, but weaker real-world risk signal"
    },
    {
      "id": "local_optional_import",
      "label": "Local optional import",
      "tradeoff": "Privacy-safe if the user provides a local list, adds setup complexity"
    },
    {
      "id": "online_api",
      "label": "Online API",
      "tradeoff": "More convenient, but introduces privacy and network dependency concerns"
    }
  ],
  "default": "local_optional_import"
}
```

Every decision is stored in the event log and project memory. Future agents must treat accepted decisions as constraints.

## 7. Context Compression

Context compression is a first-class runtime mechanism for long tasks.

Trigger policy:

```text
manual: user or agent invokes /compact
budget: context usage crosses a threshold, such as 70% or 85%
phase: research, implementation, review, or release phase completes
handoff: work is delegated to another agent or resumed later
```

Compression must preserve:

- User goal and non-negotiable constraints.
- Definition of done.
- Accepted and rejected major decisions.
- Task state.
- Modified files and reasons.
- Test and eval commands.
- Failures, fixes, and rollback decisions.
- Research findings that affected implementation.
- Open risks and next actions.

Compression should avoid preserving:

- Raw command noise after it has been summarized.
- Large file contents already available on disk.
- Dead-end exploration that has no future relevance.
- Repeated discussion that does not affect implementation.

The `/compact` command accepts focus instructions:

```text
/compact focus on API design and changed files
/compact preserve UI feedback and unresolved layout risks
/compact prepare a handoff for ReviewerAgent
```

The output is both human-readable and machine-readable. The machine-readable part should be saved as a `ContextSnapshot`.

## 8. Command Workflow Design

Commands package repeatable agent workflows.

Initial command set:

```text
/init
/plan
/brainstorm
/research
/compact
/decide
/review
/debug
/handoff
```

### 8.1 Init Command

`/init` converts a directory into an agent-ready workspace.

It creates the root contract between the user, project, runtime, and agents. This is a harness engineering concern: agents need stable entrypoints, explicit constraints, known verification commands, and durable state before they can safely operate for long tasks.

Workflow:

```text
1. Inspect workspace shape.
2. Detect project type, stack, package manager, and existing docs.
3. Detect likely test, build, lint, typecheck, and run commands.
4. Build a project map of important files and directories.
5. Create or update root guidance files.
6. Create initial task board and context snapshot.
7. Create default runtime policies.
8. Ask the user only if major initialization choices are ambiguous.
```

Root guidance layout:

```text
AGENTS.md
.agent/
  project.json
  policies.json
  context/
    root_snapshot.json
  tasks/
    backlog.json
  runs/
  memory/
```

`AGENTS.md` should contain human-readable guidance:

```text
Project purpose
Non-goals
Architecture notes
Build/test/run commands
Coding conventions
UI/design conventions
Safety boundaries
Decision granularity
Agent operating rules
```

`.agent/project.json` should contain machine-readable metadata:

```json
{
  "name": "mult-agent-code",
  "workspace_type": "planning_workspace",
  "languages": ["markdown"],
  "package_managers": [],
  "commands": {
    "test": null,
    "lint": null,
    "build": null,
    "run": null
  },
  "important_paths": ["docs/", "docs/zh/"],
  "protected_paths": [".env", "secrets/", ".git/"],
  "decision_granularity": "balanced"
}
```

`/init` must be idempotent. It can update generated sections, but it must not overwrite user-authored guidance without explicit approval.

When `/init` detects a major branch decision, such as choosing Python or Node.js for a new runtime, it should create a `DecisionPoint` instead of silently locking the project into one path.

### 8.2 Brainstorm Command

`/brainstorm` is used when the problem is broad, creative, under-specified, or has many possible product directions.

Workflow:

```text
1. Restate the goal and constraints.
2. Generate diverse candidate directions.
3. Cluster overlapping ideas.
4. Score candidates by value, feasibility, cost, risk, novelty, and fit.
5. Identify must-have baseline capabilities.
6. Recommend one or more paths.
7. Create tasks, experiments, or user decision points.
```

Output:

```json
{
  "topic": "password testing tool",
  "candidates": [
    {
      "name": "local privacy-first password lab",
      "score": 0.86,
      "strengths": ["useful", "safe", "buildable"],
      "risks": ["must avoid misleading security claims"]
    }
  ],
  "recommended": "local privacy-first password lab",
  "created_tasks": ["T-010", "T-011"],
  "decision_points": ["D-004"]
}
```

`/brainstorm` should not directly implement code. It produces direction, options, tasks, and decision points.

### 8.3 Handoff Command

`/handoff` creates a continuation package for another agent or future session.

It should include:

- ContextSnapshot.
- Current task board.
- Recent diffs.
- Verification status.
- Known risks.
- Recommended next command.

## 9. Harness Engineering Principles

The runtime should be designed as a harness around unreliable model workers. Its job is to make agent behavior observable, bounded, recoverable, and verifiable.

Core harness principles:

- Stable root context: every run starts from root guidance and current context snapshot.
- Explicit state: goals, tasks, decisions, patches, tool calls, and evals are stored as durable artifacts.
- Narrow tools: agents use structured tools where possible, not only raw shell.
- Permission boundaries: role, state, and path permissions are enforced by the runtime.
- Phase gates: plan, implement, verify, review, and keep/discard are distinct gates.
- Recovery paths: failed edits can be rolled back, retried, or escalated.
- Budget control: token, time, experiment, and tool budgets are explicit.
- Handoffs: long tasks can be compacted and resumed without losing intent.
- User steering: major branch decisions become `DecisionPoint` objects.
- Root file discipline: project-level guidance is kept in stable files, not only transient chat context.

## 10. Tool Design

Tools should be structured, narrow, and observable.

Initial tools:

```text
read_file
list_files
search_code
apply_patch
run_command
run_tests
run_lint
run_typecheck
create_worktree
diff_workspace
rollback_workspace
query_web
query_docs
take_screenshot
write_memory
read_memory
create_task
update_task
submit_artifact
```

Tool response format:

```json
{
  "ok": true,
  "summary": "3 tests passed",
  "data": {},
  "warnings": [],
  "error": null
}
```

## 11. Permission Model

Permissions are role-based and state-based.

Example:

```json
{
  "CoderAgent": {
    "allowed_tools": ["read_file", "search_code", "apply_patch", "run_tests"],
    "write_scope": "assigned_workspace"
  },
  "ReviewerAgent": {
    "allowed_tools": ["read_file", "search_code", "diff_workspace"],
    "write_scope": "none"
  },
  "ResearchAgent": {
    "allowed_tools": ["query_web", "query_docs", "write_memory", "create_task"],
    "write_scope": "research_artifacts"
  }
}
```

High-risk tool calls are intercepted by the runtime.

## 12. Workspace Strategy

MVP:

- One main workspace.
- One temporary implementation workspace.
- Patch diff before keep/discard.

Future:

- One worktree per agent.
- Merge queue.
- Conflict resolver.
- Container isolation.

Recommended layout:

```text
.agent/
  project.json
  policies.json
  context/
    root_snapshot.json
    handoffs/
  runs/
    run-2026-04-27-001/
      goal_spec.json
      task_plan.json
      events.jsonl
      experiments.jsonl
      final_report.md
  memory/
  workspaces/
  artifacts/
```

## 13. Memory Design

Memory layers:

```text
User memory: preferences and long-term goals.
Project memory: architecture and decisions.
Task memory: current active context.
Experiment memory: what worked and failed.
Research memory: claims, evidence, citations.
Decision memory: user choices and rejected alternatives.
Context memory: compressed snapshots and handoff packages.
```

MVP storage:

- SQLite for structured records.
- Files for artifacts.

Future storage:

- Vector database for semantic retrieval.
- Knowledge graph for entity relationships.

## 14. Evaluation Design

The system evaluates both outcomes and trajectories.

Outcome eval:

- Tests passed.
- Build passed.
- App starts.
- UI usable.
- Report complete.
- Metrics improved.

Trajectory eval:

- Tool calls were relevant.
- Agent did not loop.
- Agent did not bypass rules.
- Scope stayed controlled.
- Cost stayed within budget.
- Failures were handled.

## 15. Auto-Correction Design

Failure repair loop:

```text
capture_failure
  -> summarize_evidence
  -> propose_hypotheses
  -> choose_minimal_patch
  -> apply_patch
  -> rerun_evaluator
  -> keep_or_rollback
```

Retry policy:

```text
max_retries_per_task: 3
max_retries_per_failure_type: 2
rollback_on_regression: true
escalate_to_user_on_safety_risk: true
```

## 16. Research Loop Design

Research flow:

```text
research_question
  -> source_discovery
  -> source_filtering
  -> claim_extraction
  -> evidence_mapping
  -> hypothesis_generation
  -> experiment_design
  -> task_creation
```

Research outputs should always be actionable. A useful research result creates one or more:

- implementation task
- experiment task
- architecture decision
- memory entry
- report section

## 17. UI/Experience Design

The UI/Experience agent chooses output based on task fit.

Decision factors:

- Is the user repeatedly interacting with data?
- Is the output meant for reading or operating?
- Does it need real-time state?
- Does it need visual inspection?
- Does it need to be shared?
- Does it need automation more than interface?

Examples:

```text
Knowledge base -> local web app
Batch file renamer -> desktop app or CLI with preview
Research summary -> PDF plus markdown source
Agent monitoring -> dashboard
Data cleanup -> CLI plus report
```

## 18. Model Provider Design

Use a provider abstraction.

```text
ModelClient
  -> chat()
  -> tool_call()
  -> embed()
  -> rerank() optional
```

Provider targets:

- Zhipu.
- MiniMax.
- DeepSeek.
- OpenRouter.
- Local OpenAI-compatible servers.

Model routing:

```text
planning: strong model
architecture: strong model
coding: medium or strong model
review: strong model
summarization: cheap model
classification: cheap model
embedding: embedding model
```

## 19. MVP Implementation Plan

### Phase 1: Runtime Skeleton

- CLI entrypoint.
- `/init` command.
- Run directory creation.
- GoalSpec generation.
- Event log.
- Basic task board.
- Basic decision manager.
- Basic command registry.
- Context snapshot writer.

### Phase 2: Tool Registry

- File tools.
- Search tools.
- Patch tools.
- Command/test tools.
- Tool call logging.

### Phase 3: Agent Loop

- PlannerAgent.
- CoderAgent.
- TesterAgent.
- ReviewerAgent.
- Reporter.

### Phase 4: Keep/Discard Loop

- Workspace diff.
- Verification command.
- Experiment log.
- Rollback on failure.

### Phase 5: Research and UI Agents

- Research task generation.
- UI output recommendation.
- Web/PDF/report task creation.

### Phase 6: Memory

- SQLite memory.
- Run summaries.
- Relevant memory retrieval.

## 20. Open Design Questions

1. Should the first implementation use Python or Node.js?
2. Should workspaces use Git worktree from the start?
3. Should the first UI be a dashboard or only final reports?
4. Which model provider should be the default?
5. Should research use web search APIs, local paper corpora, or both?
6. How strict should human approval be for file edits and shell commands?
7. What should the default decision granularity be: `autopilot`, `balanced`, `collaborative`, or `manual`?
8. What context threshold should trigger automatic compaction?
9. Which commands should agents be allowed to invoke without user approval?
10. What root files should be generated by default, and which should remain optional?

## 21. Recommended First Technical Choices

For the first real implementation:

- Language: Python for orchestration.
- Storage: SQLite plus JSONL event logs.
- Workspaces: Git worktree when the target project is a Git repo; temp copy otherwise.
- Model API: OpenAI-compatible adapter.
- CLI: Typer or Click.
- Web UI later: FastAPI plus React, or a simple local dashboard after the core loop works.
- Patch format: unified diff.
- Reports: Markdown first, PDF later.
