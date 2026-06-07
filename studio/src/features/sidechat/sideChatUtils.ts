import type { StudioEvent } from "../../types";

export type SideChatItem =
  | { kind: "user"; id: string; text: string; at: string }
  | { kind: "assistant"; id: string; text: string; at: string }
  | { kind: "error"; id: string; text: string; at: string };

export function isSideChatEvent(event: StudioEvent): boolean {
  return event.display_level === "side" || event.ui_intent === "side_chat";
}

export function buildSideChatItems(events: StudioEvent[]): SideChatItem[] {
  const items: SideChatItem[] = [];
  for (const event of events) {
    if (!isSideChatEvent(event)) continue;
    if (event.type === "user_message" && event.content_delta) {
      items.push({
        kind: "user",
        id: event.event_id,
        text: event.content_delta,
        at: event.created_at,
      });
      continue;
    }
    if (event.type === "final_answer" && event.content_delta) {
      items.push({
        kind: "assistant",
        id: event.event_id,
        text: event.content_delta,
        at: event.created_at,
      });
      continue;
    }
    if (event.type === "error") {
      items.push({
        kind: "error",
        id: event.event_id,
        text: event.content_delta || event.summary || "Something went wrong.",
        at: event.created_at,
      });
    }
  }
  return items.sort((a, b) => a.at.localeCompare(b.at));
}

export function sideChatPending(events: StudioEvent[]): boolean {
  const sideEvents = events.filter(isSideChatEvent);
  const lastUser = [...sideEvents].reverse().find((event) => event.type === "user_message");
  if (!lastUser) return false;
  const lastUserAt = lastUser.created_at;
  const hasReply = sideEvents.some(
    (event) =>
      (event.type === "final_answer" || event.type === "error")
      && event.created_at >= lastUserAt,
  );
  return !hasReply;
}
