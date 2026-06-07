import type { StudioEvent } from "../types";

export function eventTimeValue(event: StudioEvent): number {
  const value = Date.parse(String(event.created_at ?? ""));
  if (Number.isFinite(value)) return value;
  const sequence = Number((event as unknown as Record<string, unknown>).sequence);
  if (Number.isFinite(sequence)) return sequence;
  return 0;
}

export function mergeEventLists(prev: StudioEvent[], incoming: StudioEvent[]): StudioEvent[] {
  const existingIds = new Set(prev.map((event) => event.event_id));
  const fresh = incoming.filter((event) => !existingIds.has(event.event_id));
  if (!fresh.length) return prev;
  return [...prev, ...fresh].sort((a, b) => eventTimeValue(a) - eventTimeValue(b));
}
