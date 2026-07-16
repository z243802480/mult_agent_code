import type { StudioSession } from "../../types";

export type SessionListFilter = "all" | "recent" | "archived";

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
  // Archived sessions live ONLY in their own tab; the working tabs never show them (G3).
  if (filter === "archived") return sorted.filter((session) => session.archived_at);
  const active = sorted.filter((session) => !session.archived_at);
  if (filter === "all") return active;
  const cutoff = Date.now() - RECENT_MS;
  return active.filter((session) => sessionTimestamp(session) >= cutoff);
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

// Letters from scripts unrelated to a Chinese/English title — Latin-ext & IPA, spacing modifiers,
// Greek/Coptic, Cyrillic, Armenian, Hebrew, Arabic. When a UTF-8 goal is wholesale-misdecoded through
// the wrong codepage, the bytes that DON'T become U+FFFD scatter into these blocks. A genuine title
// never mixes them into Chinese, so two or more surviving here is a reliable "this is debris" signal.
const STRAY_SCRIPT = /[À-ɏʰ-˿Ͱ-ۿ]/g;

export function cleanSessionTitle(value: string | null | undefined): string {
  // A display guard must never throw — untitled sessions carry no title field at all.
  if (value == null) return "未命名会话";
  // Sessions created from a mis-encoded console (a GBK terminal whose UTF-8 bytes were decoded with
  // the wrong codepage) stored mojibake in session.json. Two shapes appear: (1) a good UTF-8 prefix
  // with a mangled tail of lone surrogates / U+FFFD — e.g. "用一句话说明素数的定义�\udc80\udc82", where
  // only the trailing "。" was lost; and (2) a wholly misdecoded string — e.g. the real
  // "…回答:1+1等于几?" landing as "��仰�ش�:1+1�…", where the U+FFFD strip
  // still leaves a stray ideograph ("仰") plus scattered IPA/Cyrillic/Arabic letters. U+FFFD and lone
  // surrogates only ever come from a FAILED decode, so we strip them: shape (1) recovers its Chinese
  // cleanly; shape (2) must collapse to the unnamed fallback. Studio-created sessions (BFF / browser,
  // natively UTF-8) never hit this — verified end-to-end: a Chinese title POSTed via fetch round-trips
  // byte-perfect. This is a read-side guard for historical CLI/curl data; the deeper write-side cause
  // is the CLI decoding a non-UTF-8 console goal, out of the browser path.
  // Strip first — never `.test()`/`.exec()` a shared /g regex for a boolean (its stateful lastIndex
  // would corrupt alternate calls); `.replace()` and `.match()` don't carry lastIndex across calls.
  const stripped = value.replace(LONE_SURROGATE, "").replace(/�/g, "");
  const removed = value.length - stripped.length;
  const text = stripped
    .replace(/\?{2,}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "未命名会话";
  // No decode failure → a genuine title (this is the path every Studio/browser session takes).
  if (removed === 0) return text;
  // A decode DID fail. Decide salvage vs fallback by WHAT survived, not by how much was lost — a long
  // valid Chinese prefix minus its trailing char is worth keeping, but a wholesale misdecode leaves
  // only debris: a couple of bytes that happened to land on valid codepoints. Fall back when nothing
  // readable (CJK ideograph / ASCII word char) survived, or when 2+ stray foreign-script letters did
  // — the fingerprint of shape (2) that the old "any CJK survived?" check let through (a coincidental
  // "仰" kept the whole wreck on screen).
  const readable = (text.match(/[一-鿿A-Za-z0-9]/g) || []).length;
  const stray = (text.match(STRAY_SCRIPT) || []).length;
  if (readable === 0 || stray >= 2) return "未命名会话";
  return text;
}

export function sessionInitial(title: string): string {
  const cleaned = cleanSessionTitle(title);
  const match = cleaned.match(/[A-Za-z0-9\u4e00-\u9fff]/);
  return (match?.[0] ?? "?").toUpperCase();
}

export function sessionPreview(session: StudioSession): string {
  const raw = String(session.goal_preview ?? "").trim();
  if (!raw) return "";
  // goal_preview is mojibake-prone the same way title is (both come from the same goal text). Run it
  // through the same guard so a corrupted preview doesn't leak debris into the subtitle / tooltip /
  // accessible name — when it cleans to the unnamed fallback, show nothing rather than the wreck.
  const cleaned = cleanSessionTitle(raw);
  return cleaned === "未命名会话" ? "" : cleaned;
}

export function sessionHint(session: StudioSession, title: string, preview: string): string {
  return (
    [preview, new Date(session.updated_at).toLocaleString()].filter(Boolean).join(" · ") || title
  );
}
