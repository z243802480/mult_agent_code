// session.json read/write hardening.
//
// Found via a real corruption (2026-07-17): session.json ended in `}}` — a valid object plus one
// stray byte — and the session silently VANISHED from the sidebar (listSessions → readSession →
// JSON.parse throws → dropped). Root cause: session.json has multiple read-modify-write writers
// (the event bus updates title/updated_at on every appended event; user actions rename/archive/
// soft-delete), all using bare fs.writeFile. Concurrent writeFile calls interleave: a shorter body
// written over a longer one leaves the old tail behind. Two layers of defense:
//   1. parseSessionText salvages a readable object out of trailing garbage (existing corrupt files
//      come back to the list without manual repair).
//   2. writeSessionJson makes every write atomic (tmp + rename) and serializes writers per file,
//      so the race cannot produce a torn file again.
import { promises as fs } from "node:fs";

/** Parse session.json text; on failure, salvage the longest valid object prefix (trailing-garbage
 *  corruption). Returns null when nothing parseable remains. */
/**
 * Whether a parsed value is actually a session rather than merely valid JSON.
 *
 * The salvage below accepts the longest prefix that PARSES, which is not the same as the longest
 * prefix that is a session: a mangled file could yield an array, a number, or an object whose id
 * was never written. Callers all treat null as "unreadable" and rebuild from the session id they
 * already hold, so handing them a non-session would be strictly worse than handing them nothing.
 */
function isSessionShape(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return typeof value.session_id === "string" && value.session_id.length > 0;
}

export function parseSessionText(raw) {
  const text = String(raw ?? "").trim();
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    if (isSessionShape(parsed)) return parsed;
  } catch {
    // fall through to salvage
  }
  let end = text.lastIndexOf("}");
  while (end > 0) {
    try {
      const parsed = JSON.parse(text.slice(0, end + 1));
      if (isSessionShape(parsed)) return parsed;
    } catch {
      // keep walking back
    }
    end = text.lastIndexOf("}", end - 1);
  }
  return null;
}

// Per-file write queue: writes stay ordered and never interleave within this process.
const writeQueues = new Map();

/** Atomically write session.json: serialized per file, tmp + rename (all-or-nothing). */
export function writeSessionJson(file, session) {
  const prev = writeQueues.get(file) ?? Promise.resolve();
  const next = prev.then(async () => {
    const body = JSON.stringify(session, null, 2);
    const tmp = `${file}.tmp-${process.pid}-${Math.random().toString(16).slice(2)}`;
    await fs.writeFile(tmp, body, "utf8");
    try {
      await fs.rename(tmp, file);
    } catch {
      // Windows can refuse a rename onto a concurrently-open target; a direct write of the same
      // body is still strictly better than losing the update. Clean the tmp either way.
      await fs.writeFile(file, body, "utf8");
      await fs.rm(tmp, { force: true }).catch(() => {});
    }
  });
  writeQueues.set(
    file,
    next.catch(() => {}),
  );
  return next;
}
