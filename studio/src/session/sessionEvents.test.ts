import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";
// @ts-expect-error - server-side lib module, no type declarations (plain .mjs).
import { createEventBus } from "../../lib/event-bus.mjs";
// @ts-expect-error - server-side lib module, no type declarations (plain .mjs).
import { parseSessionEvents } from "../../lib/session-events.mjs";

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("Studio session events", () => {
  it("keeps concurrent Node appends in persisted seq order", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "asteria-event-bus-test-"));
    roots.push(root);
    const sessionPath = (sid: string, name?: string) =>
      path.join(root, sid, ...(name ? [name] : []));
    const bus = createEventBus({ sessionPath, getWorkspace: () => root });
    const sid = "session-test";
    await Promise.all(
      Array.from({ length: 200 }, (_, n) =>
        bus.appendEvent(sid, { type: "assistant_delta", content_delta: String(n) }),
      ),
    );
    const raw = await readFile(sessionPath(sid, "events.jsonl"), "utf8");
    const events = raw
      .trimEnd()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(events).toHaveLength(200);
    expect(events.map((event) => event.seq)).toEqual(Array.from({ length: 200 }, (_, n) => n));
    expect(events.map((event) => event.content_delta)).toEqual(
      Array.from({ length: 200 }, (_, n) => String(n)),
    );
  });

  it("keeps rows parseable while the Python model sink writes concurrently", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "asteria-cross-process-events-test-"));
    roots.push(root);
    const sid = "session-test";
    const sessionPath = (sessionId: string, name?: string) =>
      path.join(root, sessionId, ...(name ? [name] : []));
    const bus = createEventBus({ sessionPath, getWorkspace: () => root });
    const file = sessionPath(sid, "events.jsonl");
    // Exercise the real Python sink and its OS append call while Node appends to the same file.
    const python = spawn(
      process.env.ASTERIA_PYTHON || "python",
      [
        "-c",
        "from asteria_runtime.models.studio_event_sink import StudioModelEventSink; s=StudioModelEventSink(); [s.model_delta(str(i), provider='fake', model='test') for i in range(100)]",
      ],
      {
        env: {
          ...process.env,
          PYTHONPATH: path.resolve("..", "src"),
          ASTERIA_STUDIO_EVENT_SINK: file,
          ASTERIA_STUDIO_SESSION_ID: sid,
          ASTERIA_STUDIO_PHASE: "execute",
        },
      },
    );
    let stderr = "";
    python.stderr.on("data", (chunk) => (stderr += chunk.toString()));
    const pythonDone = new Promise<void>((resolve, reject) => {
      python.on("error", reject);
      python.on("close", (code) =>
        code === 0 ? resolve() : reject(new Error(`Python sink exited ${code}: ${stderr}`)),
      );
    });
    const [pythonError] = await Promise.all([
      pythonDone.then(
        () => null,
        (error: Error) => error,
      ),
      Promise.all(
        Array.from({ length: 100 }, (_, n) =>
          bus.appendEvent(sid, { type: "assistant_delta", content_delta: String(n) }),
        ),
      ),
    ]);
    if (pythonError) throw pythonError;
    const raw = await readFile(file, "utf8");
    const rows = raw
      .trimEnd()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(rows).toHaveLength(200);
    expect(rows.filter((row) => row.type === "model_delta")).toHaveLength(100);
    expect(rows.filter((row) => row.type === "assistant_delta")).toHaveLength(100);
  });

  it("drops a damaged row without turning internal metadata into conversation text", () => {
    const raw = [
      JSON.stringify({ type: "user_message", content_delta: "start" }),
      'rovider_call_seconds":180,"source":"runtime_user_progress"}',
      JSON.stringify({ type: "final_answer", content_delta: "done" }),
    ].join("\n");
    const events = parseSessionEvents(raw);
    expect(events.map((event: { type: string }) => event.type)).toEqual([
      "user_message",
      "final_answer",
    ]);
    expect(events.map((event: { seq: number }) => event.seq)).toEqual([0, 2]);
    expect(JSON.stringify(events)).not.toContain("provider_call_seconds");
  });
});
