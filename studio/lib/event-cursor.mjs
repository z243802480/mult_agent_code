// Incremental-replay cursor for session events.
//
// Every event carries a monotonic per-session `seq` (stamped by the event bus). A client tells the
// server the highest seq it already holds; the server replays only what is newer. Without this, every
// reconnect and every fallback poll re-read and re-pushed the ENTIRE transcript — so a dropped
// connection got more expensive the longer the run had been going, which is precisely backwards.

/** The client's cursor. Absent/garbage means "I have nothing" → full replay. -1 so seq 0 is included. */
export function parseSince(raw) {
  if (raw === null || raw === undefined || raw === "") return -1;
  const value = Number(raw);
  return Number.isFinite(value) ? value : -1;
}

/**
 * Events strictly newer than the cursor. Events with no `seq` (written before this existed, or
 * unparseable lines) are always kept: dropping them would silently lose transcript.
 */
export function eventsAfter(events, since) {
  if (since < 0) return events;
  return events.filter((event) => typeof event?.seq !== "number" || event.seq > since);
}
