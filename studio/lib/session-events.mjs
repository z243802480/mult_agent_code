import { redact } from "./text-utils.mjs";

/** A damaged JSONL row is storage corruption, never user-authored conversation text. */
export function parseSessionEvents(raw) {
  const events = [];
  for (const [index, line] of String(raw).split(/\r?\n/).entries()) {
    if (!line) continue;
    let event;
    try {
      event = redact(JSON.parse(line));
    } catch {
      continue;
    }
    if (!event || typeof event !== "object" || Array.isArray(event)) continue;
    if (typeof event.seq !== "number") event.seq = index;
    events.push(event);
  }
  return events;
}
