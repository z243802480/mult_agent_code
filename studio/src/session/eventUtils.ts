import type { StudioEvent } from "../types";

/**
 * Parsed event time in ms-epoch, or NaN when the event carries no parseable `created_at`.
 * NOTE: we deliberately do NOT fall back to a raw `sequence` integer here. A per-source sequence
 * (1, 2, 3…) lives on a different numeric axis than an ms-epoch timestamp (~1.7e12); mixing them in
 * one `a - b` comparator teleported every sequence-only event to the very front of the thread (L8).
 * Events without a timestamp are instead ordered by their insertion position (see mergeEventLists),
 * which already reflects arrival/file order for both session and runtime event sources.
 */
export function eventTimeValue(event: StudioEvent): number {
  return Date.parse(String(event.created_at ?? ""));
}

/**
 * Which run should the evidence panel (runDetail) track? Normally the run behind the latest
 * meaningful progress event (tool_end / final_answer / error). But a run that PAUSED for the user's
 * decision must win: its DecisionCard resolves against runDetail.run_id, so runDetail has to point at
 * exactly that run — otherwise the resolve call targets a stale run the server rejects as "decision is
 * not pending" (L9), or, when the decision arrived before any tool ran, runDetail is null and the
 * actionable card never renders (M7). A pending decision is a job-less waiting_user decision_request/
 * ask carrying a run_id. We pick whichever of the two appears LATER in the stream, so once the
 * decision resolves and fresh tool events arrive, tracking resumes normally.
 */
export function pickRunTriggerEvent(events: StudioEvent[]): StudioEvent | null {
  let decisionIdx = -1;
  let progressIdx = -1;
  events.forEach((event, index) => {
    if (!event.run_id) return;
    if (
      !event.job_id &&
      event.status === "waiting_user" &&
      ["decision_request", "ask"].includes(String(event.transcript_kind ?? ""))
    ) {
      decisionIdx = index;
    }
    if (["tool_end", "final_answer", "error"].includes(String(event.type ?? ""))) {
      progressIdx = index;
    }
  });
  const idx = decisionIdx >= progressIdx ? decisionIdx : progressIdx;
  return idx >= 0 ? events[idx] : null;
}

export function mergeEventLists(prev: StudioEvent[], incoming: StudioEvent[]): StudioEvent[] {
  const existingIds = new Set(prev.map((event) => event.event_id));
  const fresh = incoming.filter((event) => !existingIds.has(event.event_id));
  if (!fresh.length) return prev;
  // Assign every event a numeric time KEY, then sort on (key, insertion-index). Events with a
  // parseable created_at use it; events without inherit the last seen timestamp (carry-forward) so
  // they stay adjacent to where they arrived rather than teleporting to the epoch origin. The key is
  // fixed up-front, so the comparator is a consistent total order. A naive `eventTimeValue(a) -
  // eventTimeValue(b)` with a per-event NaN/sequence fallback was INTRANSITIVE — an untimestamped
  // event whose index landed between two timestamped events with the opposite time-order created a
  // sort cycle that silently mis-ordered timestamped events too (L8).
  let lastTs = 0;
  return [...prev, ...fresh]
    .map((event, index) => {
      const ts = eventTimeValue(event);
      if (Number.isFinite(ts)) lastTs = ts;
      return { event, index, key: Number.isFinite(ts) ? ts : lastTs };
    })
    .sort((a, b) => (a.key !== b.key ? a.key - b.key : a.index - b.index))
    .map((entry) => entry.event);
}
