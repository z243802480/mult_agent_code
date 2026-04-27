# Multi-Agent Autonomous Development System - Project Goal

## 1. Vision

Build a local-first autonomous development workbench that can take a small human goal and continuously turn it into usable software, research outputs, reports, or interactive systems through a controlled multi-agent loop.

The system is not a chatroom for agents. It is an agent runtime that converts model calls into verified work artifacts: plans, tasks, code patches, experiments, UI outputs, reports, tests, reviews, and reusable memory.

## 2. Core Goal

Given a compact system goal from the user, the platform should:

1. Clarify the goal into a structured specification.
2. Infer missing but reasonable requirements from the goal, domain, and intended use.
3. Research comparable tools, common workflows, and standard feature sets when the user goal is underspecified.
4. Decide whether research, implementation, UI, reports, experiments, or all of them are needed.
5. Decompose the goal into trackable tasks.
6. Assign tasks to specialized agents.
7. Let agents work in isolated workspaces.
8. Produce code, documents, UI, reports, and experiments.
9. Verify outputs with tests, evaluations, screenshots, and acceptance checks.
10. Automatically repair failures.
11. Keep successful changes and roll back failed attempts.
12. Persist useful knowledge into memory for future runs.

## 3. Self-Iteration and Autonomous Requirement Expansion

The system must not behave like a one-step instruction executor. It should treat a short user goal as the seed of a complete product, research, or engineering task.

When the user gives a broad goal, the system should autonomously:

1. Understand the target domain deeply enough to identify expected capabilities.
2. Research common tools, workflows, edge cases, user expectations, and quality standards.
3. Expand the initial goal into a reasonable product requirement set.
4. Separate must-have, should-have, and optional features.
5. Build a first usable version.
6. Evaluate whether the result is merely functional or actually useful.
7. Create follow-up tasks for missing capabilities, poor UX, weak tests, or incomplete documentation.
8. Iterate until the system reaches a usable and relatively pleasant baseline, or until budget and safety limits are reached.

Example:

If the user says "build a password testing tool", the system should not only create a text box and a score. A competent ProductAgent and ResearchAgent should discover that common tools may include password strength scoring, entropy estimation, common password detection, breach-list checking when allowed, hashing examples, encoding and decoding helpers, random password generation, passphrase generation, policy checks, local-only privacy guarantees, and clear security warnings. The system should then decide which of these are appropriate for the user's context, implement a coherent subset, and evaluate whether the final tool is actually usable.

This self-iteration is driven by model judgment, research evidence, product heuristics, automated checks, and agent review. The target is not infinite perfection. The target is a reasonable stopping point where the result is usable, coherent, documented, tested, and noticeably better than a literal one-step implementation.

## 4. Product Positioning

This project is a self-evolving R&D and software-building workbench.

It combines ideas from:

- Agentic coding systems, such as Claude Code, OpenCode, OpenHands, and SWE-agent.
- Autonomous experiment loops, such as Karpathy's autoresearch.
- Research automation systems, such as AutoResearchClaw, ARI, and AI Scientist.
- Local knowledge-base systems with retrieval, memory, and structured project context.

The system should learn from public architecture ideas but must not reuse leaked or proprietary source code.

## 5. Primary Use Cases

### 5.1 Build Small Software Tools

Example:

"Build a local markdown knowledge-base system with semantic search and Q&A."

Expected output:

- Runnable local application.
- Import/index pipeline.
- Search and Q&A UI.
- Tests.
- README.
- Final implementation report.

### 5.2 Autonomously Expand Vague Product Goals

Example:

"Build a password testing tool."

Expected output:

- Product research on common password and encoding/security utility tools.
- Expanded requirements with must-have and optional features.
- Local-first implementation with privacy-safe behavior.
- Strength scoring, policy checks, generation helpers, and selected encoding/hash utilities when appropriate.
- Clear warnings about what the tool does and does not prove.
- Usability review and follow-up iteration before final report.

### 5.3 Build Idea-Driven Mini Systems

Example:

"Think of several useful personal automation tools and implement the best one."

Expected output:

- Idea list with selection rationale.
- Product spec.
- Runnable prototype.
- UI or CLI depending on use case.

### 5.4 Research and Reproduce Ideas

Example:

"Research hybrid retrieval methods for local knowledge bases and implement the best one."

Expected output:

- Literature and project survey.
- Structured claims and evidence.
- Implementation plan.
- Experiment loop.
- Benchmark results.
- Kept or discarded patches.

### 5.5 Generate Reports or Knowledge Artifacts

Example:

"Analyze a folder of notes and generate a strategic PDF report."

Expected output:

- Data ingestion.
- Analysis.
- PDF or web report.
- Traceable source references.

### 5.6 Improve Existing Codebases

Example:

"Make this project easier to use and fix obvious bugs."

Expected output:

- Repository scan.
- Improvement plan.
- Patches.
- Tests.
- Review summary.

## 6. Success Criteria

The MVP is successful when it can:

1. Accept a natural-language goal.
2. Produce a structured goal spec and task plan.
3. Expand at least simple underspecified goals into reasonable acceptance criteria.
4. Use at least one coding agent to edit files.
5. Run verification commands.
6. Detect failure and attempt automatic repair.
7. Record every attempt in an experiment log.
8. Keep successful patches and discard failed ones.
9. Generate a final report with what changed, what passed, what failed, and what remains.

The full system is successful when it can:

1. Run multiple agents concurrently with isolated workspaces.
2. Use research outputs to create implementation tasks.
3. Autonomously expand vague goals into coherent product requirements and implementation plans.
4. Build appropriate experience outputs, such as web apps, CLI tools, PDF reports, or dashboards.
5. Maintain long-term memory across projects.
6. Evaluate agent trajectories, not only final output.
7. Continue self-iteration until the output is usable, coherent, and relatively good, not merely technically present.
8. Improve through repeatable workflows, skills, commands, and evals.

## 7. Non-Goals

The first versions should not try to:

- Replace a full engineering team.
- Run unrestricted shell access without policy controls.
- Build a huge no-code platform before the agent runtime is stable.
- Depend on one proprietary model provider.
- Optimize for beautiful dashboards before the core loop works.
- Let many agents freely chat without task, artifact, and evaluation discipline.
- Pursue endless perfection after the result has reached the agreed useful baseline.

## 8. Guiding Principles

1. Runtime first, agents second.
2. Every model call should produce or improve an artifact.
3. Every change should be verifiable.
4. Failed attempts are expected and should be logged.
5. Keep/discard decisions should be based on frozen evaluators.
6. Tool design matters as much as prompt design.
7. Context should be retrieved and layered, not dumped.
8. Multi-agent autonomy needs workspace isolation and merge discipline.
9. UI and output format should be chosen by task needs, not by habit.
10. Research must become executable hypotheses, not passive summaries.
11. A vague but reasonable goal should be expanded into a complete, useful result.
12. The system should not wait for the user to specify every obvious product detail.
