# Multi-Agent Autonomous Development System - Requirements

## 1. Overview

This document defines the functional and non-functional requirements for a local-first multi-agent autonomous development system.

The system accepts a human goal, plans work, optionally researches, implements software or reports, verifies results, fixes failures, and records reusable memory.

## 2. User Roles

### 2.1 Human Owner

The primary user who provides goals, sets budgets, reviews major decisions, and receives final outputs.

### 2.2 Agent Runtime

The controlled execution environment that manages context, tools, workspaces, permissions, memory, logs, and evaluations.

### 2.3 Specialized Agents

Role-based model workers operating under runtime constraints.

Initial roles:

- GoalSpecAgent
- PlannerAgent
- ArchitectAgent
- ResearchAgent
- CoderAgent
- UIExperienceAgent
- TesterAgent
- ReviewerAgent
- AutoCorrectionAgent
- MemoryAgent
- ReleaseAgent

## 3. Functional Requirements

### 3.1 Goal Intake

The system must accept a natural-language goal and convert it into a structured `GoalSpec`.

The `GoalSpec` must include:

- Original user goal.
- Assumptions.
- Constraints.
- Target output format.
- Definition of done.
- Verification strategy.
- Budget limits.

### 3.2 Planning

The system must decompose the goal into milestones and tasks.

Each task must include:

- ID.
- Title.
- Description.
- Owner role.
- Dependencies.
- Acceptance criteria.
- Allowed tools.
- Expected artifacts.
- Status.

Task statuses:

- `backlog`
- `ready`
- `in_progress`
- `reviewing`
- `testing`
- `blocked`
- `done`
- `discarded`

### 3.3 Agent Runtime

The runtime must provide:

- Context manager.
- Tool registry.
- Permission manager.
- Decision manager.
- Workspace manager.
- Event log.
- Eval runner.
- Memory store.
- Budget controller.
- Recovery and rollback engine.

### 3.4 Context Management

The system must maintain layered context:

- Global instructions.
- Project instructions.
- Current task context.
- Retrieved code context.
- Retrieved research context.
- Recent trajectory summary.
- Relevant memory.

The system should avoid injecting unnecessary full-history context.

The system must support context compression for long-running tasks.

Context compression must preserve:

- Current goal and definition of done.
- Accepted user decisions.
- Active tasks and task status.
- Files changed and why.
- Tests and verification commands already run.
- Important failures and repair attempts.
- Open risks, blockers, and next actions.
- Research claims and accepted implementation hypotheses.

Compression may be triggered:

- Manually by a command such as `/compact`.
- Automatically when context usage crosses a configurable threshold.
- At phase boundaries, such as after research, after implementation, or before review.
- Before handing work to another agent.

Compression should support optional focus instructions, such as "preserve API decisions" or "focus on UI feedback".

### 3.5 Tool System

The runtime must expose structured tools instead of relying only on raw shell access.

Required tool categories:

- File read/write tools.
- Code search tools.
- Patch application tools.
- Test execution tools.
- Lint/typecheck tools.
- Web or document research tools.
- Git/worktree tools.
- Browser/screenshot tools.
- Report generation tools.
- Memory read/write tools.

Each tool call must be logged with:

- Agent ID.
- Task ID.
- Tool name.
- Input summary.
- Output summary.
- Success or failure.
- Cost and duration if available.

### 3.6 Command and Workflow System

The system must support reusable commands for common agent workflows.

Commands are not simple text shortcuts. They are named workflows with:

- Description.
- Arguments.
- Allowed tools.
- Required agent roles.
- Expected artifacts.
- Safety or approval rules.
- Optional templates or scripts.

Initial commands should include:

- `/init`: initialize an agent-ready project workspace and create root project guidance files.
- `/plan`: clarify goal, assumptions, milestones, and tasks.
- `/brainstorm`: generate, compare, and rank possible product directions or implementation ideas.
- `/research`: perform structured research and convert findings into hypotheses or tasks.
- `/compact`: compress context while preserving critical state.
- `/decide`: create a user-facing decision point.
- `/review`: review code, UX, tests, or architecture.
- `/debug`: analyze failure evidence and propose repairs.
- `/handoff`: create a machine-readable continuation package for another agent or future run.

The `/brainstorm` command must support both divergence and convergence:

1. Generate multiple ideas or solution paths.
2. Cluster similar ideas.
3. Score them against user goal, feasibility, cost, risk, and expected value.
4. Select recommended directions.
5. Create tasks, experiments, or decision points from the best candidates.

Commands should be invocable by the user and, when safe, by agents themselves.

### 3.7 Project Initialization and Root Guidance

The system must provide an initialization workflow that prepares a repository or empty directory for agentic work.

The initialization workflow should:

- Detect whether the workspace is an existing project, an empty project, or a documentation-only planning workspace.
- Create or update root guidance files that agents can reliably read before acting.
- Record the project purpose, current assumptions, constraints, and non-goals.
- Detect technology stack, package managers, test commands, build commands, and formatting commands.
- Build an initial project map of important directories, entrypoints, configuration files, and docs.
- Record safety boundaries, such as files that should not be touched without approval.
- Record coding conventions and UI/design conventions when discoverable.
- Create a default verification profile.
- Create a default decision granularity profile.
- Create an initial context snapshot.

Recommended root files:

- `AGENTS.md`: project-level instructions for all agents.
- `.agent/project.json`: structured project metadata.
- `.agent/context/root_snapshot.json`: initial machine-readable context.
- `.agent/tasks/backlog.json`: initial task board.
- `.agent/runs/`: run logs and artifacts.
- `.agent/memory/`: local project memory.

`/init` must be safe to re-run. Re-running it should update detected metadata without overwriting user-authored guidance unless explicitly requested.

The root guidance must be treated as high-priority project context by every agent.

### 3.8 Permissions

The system must enforce role-based permissions.

Examples:

- ResearchAgent can access web research tools but cannot merge code.
- ReviewerAgent can inspect diffs but should not directly modify implementation files.
- CoderAgent can edit only assigned workspace files.
- ReleaseAgent can package outputs but should not deploy without explicit approval.

High-risk operations must be blocked or require approval:

- Deleting many files.
- Reading secrets.
- Modifying environment files.
- Installing global packages.
- Pushing to remote repositories.
- Deploying to production.

### 3.9 Human Decision Interaction

The system must support interactive human steering at important decision points.

The system should not ask the user about every small implementation detail. It should continue autonomously for routine choices, but escalate major branch decisions where user intent materially affects the outcome.

Decision points may include:

- Choosing between significantly different product directions.
- Choosing output medium, such as web app, CLI, PDF report, desktop app, or API service.
- Choosing technology stack when tradeoffs are meaningful.
- Expanding scope beyond the original goal.
- Dropping or postponing an expected feature.
- Spending a large additional budget.
- Using external network services or sensitive data.
- Making irreversible or high-risk changes.
- Selecting among multiple research-backed implementation approaches.

Each user-facing decision request must include:

- A concise question.
- Recommended option.
- 2-4 concrete choices when possible.
- Tradeoffs for each choice.
- Default behavior if the user does not respond.
- Impact on budget, scope, risk, and output quality.

The decision granularity must be configurable.

Suggested modes:

- `autopilot`: ask only for safety-critical or irreversible decisions.
- `balanced`: ask for major product, architecture, budget, or privacy decisions.
- `collaborative`: ask for more frequent product and UX choices.
- `manual`: ask before significant changes or scope expansion.

The system must record each decision and use it as project memory.

### 3.10 Workspace Isolation

The system must support isolated workspaces for agents.

Preferred mechanisms:

- Git worktrees.
- Temporary branches.
- Containers for higher isolation.

Agents should submit patches, not mutate the main workspace directly in concurrent mode.

### 3.11 Research Automation

The system must support an automated research loop.

Research outputs must include:

- Sources.
- Claims.
- Evidence.
- Uncertainties.
- Candidate ideas.
- Implementation hypotheses.
- Experiment plans.

Research should create implementation tasks when useful.

### 3.12 Auto-Experiment Loop

The system must support a keep/discard loop inspired by autoresearch.

Each experiment must define:

- Baseline.
- Candidate change.
- Frozen evaluator.
- Run command.
- Metrics before.
- Metrics after.
- Decision.
- Reason.

Successful experiments are kept. Failed experiments are reverted or archived.

### 3.13 Implementation

Coder agents must:

- Read relevant context before editing.
- Make scoped changes.
- Prefer existing project conventions.
- Add tests when risk justifies it.
- Produce patch summaries.

### 3.14 UI and Experience Output

The system must include a UI/Experience agent that decides the best output form.

Possible output forms:

- Web application.
- Desktop application.
- CLI.
- TUI.
- PDF report.
- Markdown knowledge base.
- Dashboard.
- Browser extension.
- API service.

The UI/Experience agent must produce:

- Output medium recommendation.
- Interaction model.
- Primary screens or sections.
- Visual style direction.
- Usability acceptance criteria.

### 3.15 Verification

The system must run appropriate checks:

- Unit tests.
- Integration tests.
- Lint.
- Typecheck.
- Build.
- Smoke tests.
- UI screenshot checks.
- Benchmark or eval scripts.
- Report completeness checks.

The verification strategy should be selected per goal.

### 3.16 Auto-Correction

When verification fails, the system must:

1. Capture failure evidence.
2. Summarize logs.
3. Generate hypotheses.
4. Attempt a minimal fix.
5. Re-run verification.
6. Keep successful fixes.
7. Roll back failed attempts after retry limits.

### 3.17 Review

The system must review patches before merging.

Review should check:

- Correctness.
- Regression risk.
- Security issues.
- Scope creep.
- Test coverage.
- Maintainability.
- UX issues when applicable.

### 3.18 Memory

The system must store reusable memory:

- User preferences.
- Project decisions.
- Architecture notes.
- Successful patterns.
- Failed experiment lessons.
- Tooling knowledge.
- Research summaries.

Memory retrieval must be relevance-based and scoped to the current task.

### 3.19 Final Reporting

At the end of each run, the system must produce a final report:

- Goal.
- Completed tasks.
- Generated artifacts.
- Tests/evals run.
- Metrics.
- Kept changes.
- Discarded attempts.
- Remaining risks.
- Suggested next steps.

## 4. Non-Functional Requirements

### 4.1 Local-First

The system should run locally by default and store project data locally unless configured otherwise.

### 4.2 Model Agnostic

The system should support OpenAI-compatible model APIs and providers such as Zhipu, MiniMax, DeepSeek, OpenRouter, and local models.

### 4.3 Observability

Every run must be traceable through logs, task state, tool calls, model calls, patches, and eval results.

### 4.4 Cost Control

The system must support:

- Token budget.
- Time budget.
- Experiment count limit.
- Per-agent budget.
- Stop conditions.

### 4.5 Reliability

The system must tolerate:

- Model errors.
- Tool failures.
- Bad patches.
- Test failures.
- Network failures during research.

### 4.6 Extensibility

The system should support adding:

- New agents.
- New tools.
- New skills.
- New evals.
- New output formats.
- New model providers.

## 5. MVP Scope

The MVP should include:

1. CLI goal intake.
2. Structured goal spec generation.
3. Task board.
4. Single isolated workspace.
5. Planner, Coder, Tester, Reviewer, AutoCorrection, and Reporter roles.
6. Tool registry with file, search, patch, shell, and test tools.
7. Basic event log.
8. Basic decision manager with configurable decision granularity.
9. Basic command system with `/init`, `/plan`, `/brainstorm`, `/compact`, `/review`, and `/handoff`.
10. Basic keep/discard loop.
11. Final report generation.

The MVP may defer:

- Full web dashboard.
- Large-scale concurrent agents.
- Full paper ingestion.
- Advanced vector memory.
- Production deployment automation.

## 6. Future Scope

Future versions may add:

- Multi-agent parallel execution.
- Research paper ingestion and citation tracking.
- Visual dashboard for agent runs.
- PDF report generation.
- Browser-based UI inspection.
- Long-term vector memory.
- Distributed experiment runners.
- Plugin/skill marketplace.
- Human approval workflows.
