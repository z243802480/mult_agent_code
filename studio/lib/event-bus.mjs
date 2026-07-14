// Studio event bus — the shared SSE fan-out + session-event persistence layer, extracted verbatim
// from server.mjs. Both the chat job path and the runtime job path append through here, so it must
// live below them as an injected facility (see docs/zh/notes/server-mjs-split-plan.md Layer 1a).
//
// Wiring: `sessionPath` and `getWorkspace` are injected as live references — the active workspace is
// a mutable `let` in server.mjs reassigned on openWorkspace, so capturing it by value would pin the
// bus to the old repo after a switch. `sessionPath` itself reads that same live workspace.
import { existsSync, promises as fs } from "node:fs";
import { redact } from "./text-utils.mjs";
import { isSafeId } from "./workspace-paths.mjs";

export function createEventBus({ sessionPath, getWorkspace }) {
  const sseClients = new Map(); // sessionId -> Set<response>

  // Monotonic per-session cursor stamped onto every event, so a reconnecting client can ask for
  // "everything after N" instead of having the whole transcript re-read and re-pushed at it. Counting
  // the file on every append would be O(n) per event — quadratic over a long run — so the counter is
  // seeded once from the existing line count and then kept in memory. A server restart re-seeds it
  // from the file, which is why `seq` is also PERSISTED: the numbering must survive the process.
  const seqCounters = new Map(); // sessionId -> next seq
  const seqSeeding = new Map(); // sessionId -> in-flight seed promise (concurrent appends must not double-seed)

  async function nextSeq(sessionId) {
    if (!seqCounters.has(sessionId)) {
      if (!seqSeeding.has(sessionId)) {
        seqSeeding.set(
          sessionId,
          (async () => {
            const file = sessionPath(sessionId, "events.jsonl");
            let lines = 0;
            if (existsSync(file)) {
              const raw = await fs.readFile(file, "utf8");
              lines = raw.split(/\r?\n/).filter(Boolean).length;
            }
            if (!seqCounters.has(sessionId)) seqCounters.set(sessionId, lines);
          })(),
        );
      }
      await seqSeeding.get(sessionId);
    }
    const seq = seqCounters.get(sessionId);
    seqCounters.set(sessionId, seq + 1);
    return seq;
  }

  function notifySSE(sessionId, event) {
    const clients = sseClients.get(sessionId);
    if (!clients?.size) return;
    const payload = `data: ${JSON.stringify(event)}\n\n`;
    for (const res of [...clients]) {
      try {
        res.write(payload);
      } catch {
        clients.delete(res);
      }
    }
  }

  async function appendEvent(sessionId, event) {
    if (!isSafeId(sessionId)) return;
    const seq = await nextSeq(sessionId);
    const full = {
      schema_version: "0.1.0",
      event_id: `evt-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      session_id: sessionId,
      created_at: new Date().toISOString(),
      artifact_refs: [],
      evidence_refs: [],
      ...redact(event),
      seq,
    };
    await fs.mkdir(sessionPath(sessionId), { recursive: true });
    await fs.appendFile(
      sessionPath(sessionId, "events.jsonl"),
      `${JSON.stringify(full)}\n`,
      "utf8",
    );
    const sessionFile = sessionPath(sessionId, "session.json");
    if (existsSync(sessionFile)) {
      let session = {};
      try {
        const rawSession = await fs.readFile(sessionFile, "utf8");
        session = rawSession.trim() ? JSON.parse(rawSession) : {};
      } catch {
        session = {};
      }
      session.session_id = sessionId;
      session.workspace = session.workspace || getWorkspace();
      session.updated_at = full.created_at;
      if (full.type === "user_message") {
        session.title = String(full.summary || session.title || "New task").slice(0, 64);
        session.goal_preview = String(
          full.content_delta || full.summary || session.goal_preview || "",
        ).slice(0, 160);
      }
      await fs.writeFile(sessionFile, JSON.stringify(session, null, 2), "utf8");
    }
    notifySSE(sessionId, full);
    return full;
  }

  return { sseClients, notifySSE, appendEvent };
}
