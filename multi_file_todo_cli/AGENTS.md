# Agent Project Guidance

## 1. Project Purpose

This project is an agent-ready workspace. Agents must use this file as high-priority project context before planning, editing, reviewing, or reporting.

Project purpose:

```text
Initialized workspace. Update this section with the project goal.
```

## 2. Non-Goals

Agents must not silently expand the project beyond these boundaries:

```text
Not specified yet.
```

## 3. Current Assumptions

```text
Not specified yet.
```

## 4. Architecture Notes

```text
Not specified yet.
```

## 5. Commands

Use these commands when available:

```yaml
install: None
run: None
test: None
lint: None
typecheck: None
build: None
format: None
```

If a command is unknown, do not invent it. Detect it from project files or create a DecisionPoint when the choice matters.

## 6. Coding Conventions

- Follow existing project style before introducing new style.
- Prefer small, verifiable changes.
- Add tests when behavior changes.
- Avoid unrelated refactors.
- Keep generated code readable and maintainable.

Project-specific conventions:

```text
Follow existing project conventions.
```

## 7. UI and Experience Conventions

- Choose the output medium based on the task, not habit.
- Do not create a web UI when CLI, report, or automation is the better product shape.
- If a UI is needed, define the primary workflow and acceptance criteria before implementation.

Project-specific UI notes:

```text
Choose output medium based on task fit.
```

## 8. Safety Boundaries

Protected paths:

```text
.env
.env.*
secrets/
.git/
*.pem
*.key
id_rsa
id_ed25519
```

Agents must not:

- Read secrets without explicit approval.
- Run destructive shell commands.
- Install global packages.
- Push to remote repositories.
- Deploy to production.
- Send sensitive local data to network services.

## 9. Decision Policy

Default decision granularity:

```text
balanced
```

Create a DecisionPoint for:

- Major product direction choices.
- Output medium choices.
- Technology stack choices with meaningful tradeoffs.
- Privacy, security, or network decisions.
- Scope expansion beyond the original goal.
- High additional cost.
- Irreversible or high-risk changes.

## 10. Cost Policy

Default budgets:

```yaml
max_model_calls_per_goal: 60
max_tool_calls_per_goal: 120
max_iterations_per_goal: 8
max_repair_attempts_per_task: 2
context_compaction_threshold: 0.75
```

When approaching budget:

1. Compact context.
2. Reduce candidate count.
3. Stop low-value branches.
4. Downgrade non-critical model calls.
5. Ask the user before continuing.

## 11. Agent Operating Rules

All agents must:

- Read root guidance and relevant context before acting.
- Produce durable artifacts, not only chat text.
- Use structured tools where available.
- Respect permissions and protected paths.
- Record decisions, tool calls, model calls, and artifacts.
- Verify changes before reporting success.
- Preserve user-authored content.

## 12. Handoff Requirements

Before long pauses, context compaction, or delegation, create a ContextSnapshot that preserves:

- Goal.
- Definition of done.
- Accepted decisions.
- Active tasks.
- Modified files and reasons.
- Verification results.
- Failures and repair attempts.
- Open risks.
- Next actions.
