# Multi-Agent Autonomous Development System - Architecture

## Runtime Architecture

```text
CLI / Local UI
  -> Command Router
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
  -> Tool Layer
  -> Persistence Layer
```

The orchestrator coordinates state, permissions, tasks, budgets, and artifact flow. Specialized agents provide judgment and generation under runtime control.

## Core Flow

```text
User goal or command
  -> root guidance and memory retrieval
  -> state transition
  -> agent prompt assembly
  -> tool calls and artifacts
  -> verification and review
  -> keep/discard
  -> context snapshot and memory update
  -> report or decision point
```

## State Machine

```text
INIT -> SPEC -> PLAN -> BRAINSTORM? -> DECIDE? -> RESEARCH?
  -> DESIGN -> IMPLEMENT -> VERIFY -> REVIEW -> REPAIR?
  -> KEEP_OR_DISCARD -> MEMORY_UPDATE -> REPORT -> DONE
```

## Technical Stack

Recommended MVP stack:

- Python 3.11+
- Typer for CLI
- Pydantic and JSON Schema for structured data
- Filesystem + JSONL first, SQLite later
- pytest for tests
- OpenAI-compatible model adapter
- Synchronous runtime first, async later

This stack is mainstream, lightweight, and locally controllable. The runtime should avoid early lock-in to heavyweight agent frameworks.
