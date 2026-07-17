/**
 * Pending diff line comments — "评论即指令" (G4).
 *
 * A comment is a structured reference (file + line + the diff line's text + the user's words) that
 * gets BATCHED and submitted as ONE ordinary user message through the existing channels (mid-run
 * steer while a run is in flight, a new turn when idle). Zero new backend protocol: the model simply
 * reads "针对 X 文件第 N 行的意见" in its next turn. This mirrors Claude Code desktop / GitHub
 * "pending review" semantics: comments accumulate locally, nothing is sent until 提交.
 *
 * Comments are UI intent that has not been sent yet, so they live in localStorage per session
 * (same reasoning and shape as composerQueue.ts) and survive a reload. They are cleared on submit.
 */

import { useSyncExternalStore } from "react";
import { createSessionScopedStore, type StorageLike } from "./sessionScopedStore";

export type DiffCommentAnchor = {
  /** Repo-relative path of the commented file. */
  file: string;
  /** Anchored line number, or null when the row carries none (rare: unnumbered context). */
  line: number | null;
  /** Which side the line number refers to: "new" = 修改后, "old" = 修改前 (deleted lines). */
  side: "new" | "old";
  /** The diff row's text at comment time, so the model sees the exact line even if it moves. */
  excerpt: string;
};

export type DiffComment = DiffCommentAnchor & {
  id: string;
  text: string;
};

const KEY_PREFIX = "asteria.diffComments.";

/** Bounded so a runaway UI or pathological paste cannot blow the storage quota. */
export const MAX_COMMENTS = 30;
export const MAX_COMMENT_CHARS = 2_000;
const MAX_EXCERPT_CHARS = 160;

const store = createSessionScopedStore<DiffComment>({ keyPrefix: KEY_PREFIX, sanitize });

export function commentsKey(sessionId: string): string {
  return store.key(sessionId);
}

function sanitize(items: unknown): DiffComment[] {
  if (!Array.isArray(items)) return [];
  const out: DiffComment[] = [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    if (typeof record.file !== "string" || !record.file.trim()) continue;
    if (typeof record.text !== "string" || !record.text.trim()) continue;
    out.push({
      id: typeof record.id === "string" && record.id ? record.id : `c-${out.length}`,
      file: record.file,
      line: typeof record.line === "number" && Number.isFinite(record.line) ? record.line : null,
      side: record.side === "old" ? "old" : "new",
      excerpt: typeof record.excerpt === "string" ? record.excerpt.slice(0, MAX_EXCERPT_CHARS) : "",
      text: record.text.slice(0, MAX_COMMENT_CHARS),
    });
    if (out.length >= MAX_COMMENTS) break;
  }
  return out;
}

export function loadComments(sessionId: string, storage?: StorageLike | null): DiffComment[] {
  return store.load(sessionId, storage);
}

export function saveComments(
  sessionId: string,
  comments: DiffComment[],
  storage?: StorageLike | null,
): void {
  store.save(sessionId, comments, storage);
}

// Deep consumers (InlineFileDiff in the thread, DiffPreviewSection in the panel) call the hook and
// the mutators directly — no prop drilling through six layers for a cross-cutting concern.

/** Called by the app shell whenever the active session changes; reloads that session's comments. */
export function setDiffCommentSession(sessionId: string): void {
  store.setSession(sessionId);
}

export function getDiffComments(): DiffComment[] {
  return store.getItems();
}

let nextId = 1;

export function addDiffComment(anchor: DiffCommentAnchor, text: string): void {
  const trimmed = text.trim();
  const current = store.getItems();
  if (!trimmed || !anchor.file || current.length >= MAX_COMMENTS) return;
  store.setItems([
    ...current,
    {
      id: `c-${Date.now().toString(36)}-${nextId++}`,
      file: anchor.file,
      line: anchor.line,
      side: anchor.side,
      excerpt: anchor.excerpt.slice(0, MAX_EXCERPT_CHARS),
      text: trimmed.slice(0, MAX_COMMENT_CHARS),
    },
  ]);
}

export function removeDiffComment(id: string): void {
  const current = store.getItems();
  const next = current.filter((item) => item.id !== id);
  if (next.length === current.length) return;
  store.setItems(next);
}

export function clearDiffComments(): void {
  if (!store.getItems().length) return;
  store.setItems([]);
}

/** Reactive view of the active session's pending comments. */
export function useDiffComments(): DiffComment[] {
  return useSyncExternalStore(store.subscribe, store.getItems, store.getSnapshot);
}

// ---------------------------------------------------------------------------
// Message assembly — the "structured reference" the model reads.
// ---------------------------------------------------------------------------

function lineLabel(comment: DiffComment): string {
  if (comment.line == null) return "";
  return comment.side === "old"
    ? `:${comment.line}（修改前第 ${comment.line} 行）`
    : `:${comment.line}（修改后第 ${comment.line} 行）`;
}

/**
 * One user message carrying every pending comment, ordered as written. Plain prose + quoted
 * excerpts — nothing the model needs a schema for, which is exactly why no backend change is needed.
 */
export function formatCommentsMessage(comments: DiffComment[]): string {
  const lines: string[] = ["请按下面这些针对当前工作区改动的行级评论修改代码："];
  comments.forEach((comment, index) => {
    lines.push("");
    lines.push(`${index + 1}. ${comment.file}${lineLabel(comment)}`);
    if (comment.excerpt.trim()) lines.push(`   > ${comment.excerpt.trim()}`);
    lines.push(`   意见：${comment.text}`);
  });
  return lines.join("\n");
}
