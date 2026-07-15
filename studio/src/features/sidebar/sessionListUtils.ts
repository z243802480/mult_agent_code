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

export function filterSessions(
  sessions: StudioSession[],
  filter: SessionListFilter,
): StudioSession[] {
  const sorted = [...sessions].sort((a, b) => sessionTimestamp(b) - sessionTimestamp(a));
  if (filter === "all") return sorted;
  const cutoff = Date.now() - RECENT_MS;
  return sorted.filter((session) => sessionTimestamp(session) >= cutoff);
}

export function searchSessions(sessions: StudioSession[], query: string): StudioSession[] {
  const q = query.trim().toLowerCase();
  if (!q) return sessions;
  return sessions.filter((session) => {
    const title = cleanSessionTitle(String(session.title || "")).toLowerCase();
    const preview = sessionPreview(session).toLowerCase();
    return title.includes(q) || preview.includes(q);
  });
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
  today: "今天",
  yesterday: "昨天",
  earlier: "更早",
};

export function groupSessionsByDate(
  sessions: StudioSession[],
  now = new Date(),
): GroupedSessions[] {
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

// Unpaired UTF-16 surrogates (a high surrogate not followed by a low one, or a low surrogate not
// preceded by a high one). Valid astral characters — emoji, rare CJK — always come as a HIGH+LOW pair
// and are preserved; only lone surrogates are matched. Legacy CLI sessions created from a mis-encoded
// console carry these as Python surrogateescape bytes (\udc80–\udcff) serialized into session.json.
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

export function cleanSessionTitle(value: string): string {
  // Sessions created from a mis-encoded console (a GBK terminal whose UTF-8 bytes were decoded with
  // the wrong codepage) stored mojibake in session.json. Two shapes appear: (1) a good UTF-8 prefix
  // with a mangled tail of lone surrogates / U+FFFD — e.g. "用一句话说明素数的定义�\udc80\udc82", where
  // only the trailing "。" was lost; and (2) a wholly misdecoded string of stray diacritics — e.g.
  // "ʵ��…", irrecoverable. U+FFFD and lone surrogates only ever come from a FAILED decode, so we strip
  // them: shape (1) recovers its real Chinese cleanly; shape (2) collapses to the unnamed fallback.
  // Studio-created sessions (BFF / browser, natively UTF-8) never hit this — this is a read-side guard
  // for historical CLI data. Deeper cause is write-side (the CLI should pin UTF-8 when reading the goal).
  // Strip first, then detect corruption by length delta — never `.test()` on a /g regex (its stateful
  // lastIndex, on a module-level shared object, would corrupt alternate calls). `.replace(/g)` is stateless.
  const stripped = value.replace(LONE_SURROGATE, "").replace(/�/g, "");
  const hadCorruption = stripped.length !== value.length;
  const text = stripped
    .replace(/\?{2,}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "未命名会话";
  // A decode failed AND nothing meaningful survived (no CJK ideograph, no ASCII word) → mojibake
  // remnants, not a title. A title that still carries a real word is kept (partial salvage).
  if (hadCorruption && !/[一-鿿]|[A-Za-z0-9]{2,}/.test(text)) return "未命名会话";
  return text;
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
  return (
    [preview, new Date(session.updated_at).toLocaleString()].filter(Boolean).join(" · ") || title
  );
}
