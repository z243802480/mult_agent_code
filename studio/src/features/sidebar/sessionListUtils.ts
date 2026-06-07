import type { StudioSession } from "../../types";

export type SessionListFilter = "all" | "recent";

export type SessionDateGroup = "today" | "yesterday" | "earlier";

export type GroupedSessions = {
  id: SessionDateGroup;
  label: string;
  sessions: StudioSession[];
};

const RECENT_MS = 7 * 24 * 60 * 60 * 1000;

export function sessionTimestamp(session: StudioSession): number {
  const value = Date.parse(String(session.updated_at ?? session.created_at ?? ""));
  return Number.isFinite(value) ? value : 0;
}

export function filterSessions(sessions: StudioSession[], filter: SessionListFilter): StudioSession[] {
  const sorted = [...sessions].sort((a, b) => sessionTimestamp(b) - sessionTimestamp(a));
  if (filter === "all") return sorted;
  const cutoff = Date.now() - RECENT_MS;
  return sorted.filter((session) => sessionTimestamp(session) >= cutoff);
}

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function sessionDateGroup(session: StudioSession, now = new Date()): SessionDateGroup {
  const ts = sessionTimestamp(session);
  if (!ts) return "earlier";
  const todayStart = startOfLocalDay(now);
  const yesterdayStart = todayStart - 24 * 60 * 60 * 1000;
  if (ts >= todayStart) return "today";
  if (ts >= yesterdayStart) return "yesterday";
  return "earlier";
}

const GROUP_LABELS: Record<SessionDateGroup, string> = {
  today: "Today",
  yesterday: "Yesterday",
  earlier: "Earlier",
};

export function groupSessionsByDate(sessions: StudioSession[], now = new Date()): GroupedSessions[] {
  const buckets = new Map<SessionDateGroup, StudioSession[]>([
    ["today", []],
    ["yesterday", []],
    ["earlier", []],
  ]);
  for (const session of sessions) {
    buckets.get(sessionDateGroup(session, now))!.push(session);
  }
  return (["today", "yesterday", "earlier"] as SessionDateGroup[])
    .map((id) => ({ id, label: GROUP_LABELS[id], sessions: buckets.get(id) ?? [] }))
    .filter((group) => group.sessions.length > 0);
}

export function cleanSessionTitle(value: string): string {
  const text = value.replace(/\?{2,}/g, " ").replace(/\s+/g, " ").trim();
  return text || "Untitled session";
}

export function sessionInitial(title: string): string {
  const cleaned = cleanSessionTitle(title);
  const match = cleaned.match(/[A-Za-z0-9\u4e00-\u9fff]/);
  return (match?.[0] ?? "?").toUpperCase();
}

export function sessionPreview(session: StudioSession): string {
  return String(session.goal_preview ?? "").trim();
}

export function sessionHint(session: StudioSession, title: string, preview: string): string {
  return [preview, new Date(session.updated_at).toLocaleString()].filter(Boolean).join(" · ") || title;
}
