# Asteria Studio

Local Web control surface for Asteria Runtime OS.

Studio is intentionally thin:

- The runtime remains in `asteria-runtime`.
- Studio reads runtime CLI JSON and `.asteria/` evidence.
- Studio does not read or display API keys.
- First version is read-only except evidence bundle export.

## Start

Install dependencies:

```powershell
cd studio
npm install
```

Start API and UI together:

```powershell
powershell -ExecutionPolicy Bypass -File F:\mult_agent_code\studio\start-studio.ps1
```

Or through npm:

```powershell
cd F:\mult_agent_code\studio
npm run start:studio
```

Start the local API adapter:

```powershell
npm run server -- --workspace F:\mult_agent_code --runtime-root F:\mult_agent_code
```

Start the UI in another terminal:

```powershell
npm run dev
```

Open:

```text
http://127.0.0.1:5174
```

## Build

```powershell
npm run typecheck
npm run build
```

After build, the API server can also serve the static UI:

```powershell
npm run server -- --workspace F:\mult_agent_code --runtime-root F:\mult_agent_code
```

Open:

```text
http://127.0.0.1:8787
```

## API

```text
GET  /api/health
GET  /api/overview
GET  /api/doctor
GET  /api/package-check
GET  /api/gate-status
GET  /api/runs
GET  /api/runs/:runId
GET  /api/model-routes
GET  /api/workspace-files
GET  /api/workbench-actions
GET  /api/agent-actions
GET  /api/conversations
GET  /api/conversations/:conversationId
POST /api/workspace-files/preview
POST /api/workbench-actions
POST /api/agent-actions
POST /api/conversations
POST /api/evidence-bundle
```

Conversation history is stored locally in:

```text
.asteria/studio/conversations.jsonl
```

The first version uses deterministic evidence-based replies. It does not call a model.

The primary user-facing entry is Agent Workspace: conversation, permissions, controlled actions, feedback, and artifact previews. Safe read-only and dry-run actions can execute from Studio; write-oriented real tasks are command previews until runtime policy, budget, approval, and evidence logging are wired into the UI.

The Workbench Launcher calls real runtime commands such as `init`, `plan`, limited `run`, `execute`, `review`, `resume`, `decide --list-pending`, and `promotions list`. Dashboard-style state is intentionally kept in the folded Control Room.
