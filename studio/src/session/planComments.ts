/**
 * Pending plan-step comments — G6 刀一（零后端）: "对计划第 N 步的意见" as a structured reference.
 *
 * Mirrors diffComments.ts deliberately (same persistence bounds, same module-store shape, same
 * tray): a comment on a plan step accumulates locally and is submitted through the EXISTING
 * message channels as part of one batched user message. The model reads "对计划第 2 步「写测试」：
 * 不要动 schema" in its next turn — plan revision stays a model act (ADR-0016), the harness only
 * delivers the user's words.
 */

import { useSyncExternalStore } from "react";
import { createSessionScopedStore, type StorageLike } from "./sessionScopedStore";

export type PlanComment = {
  id: string;
  /** 1-based step number as displayed in the checklist. */
  step: number;
  /** The step's title at comment time, so the reference survives plan re-numbering. */
  title: string;
  text: string;
};

const KEY_PREFIX = "asteria.planComments.";

export const MAX_PLAN_COMMENTS = 20;
export const MAX_PLAN_COMMENT_CHARS = 2_000;
const MAX_TITLE_CHARS = 120;

const store = createSessionScopedStore<PlanComment>({ keyPrefix: KEY_PREFIX, sanitize });

export function planCommentsKey(sessionId: string): string {
  return store.key(sessionId);
}

function sanitize(items: unknown): PlanComment[] {
  if (!Array.isArray(items)) return [];
  const out: PlanComment[] = [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    if (typeof record.text !== "string" || !record.text.trim()) continue;
    const step = typeof record.step === "number" && Number.isFinite(record.step) ? record.step : 0;
    if (step < 1) continue;
    out.push({
      id: typeof record.id === "string" && record.id ? record.id : `p-${out.length}`,
      step,
      title: typeof record.title === "string" ? record.title.slice(0, MAX_TITLE_CHARS) : "",
      text: record.text.slice(0, MAX_PLAN_COMMENT_CHARS),
    });
    if (out.length >= MAX_PLAN_COMMENTS) break;
  }
  return out;
}

export function loadPlanComments(sessionId: string, storage?: StorageLike | null): PlanComment[] {
  return store.load(sessionId, storage);
}

export function savePlanComments(
  sessionId: string,
  comments: PlanComment[],
  storage?: StorageLike | null,
): void {
  store.save(sessionId, comments, storage);
}

export function setPlanCommentSession(sessionId: string): void {
  store.setSession(sessionId);
}

export function getPlanComments(): PlanComment[] {
  return store.getItems();
}

let nextId = 1;

export function addPlanComment(step: number, title: string, text: string): void {
  const trimmed = text.trim();
  const current = store.getItems();
  if (!trimmed || step < 1 || current.length >= MAX_PLAN_COMMENTS) return;
  store.setItems([
    ...current,
    {
      id: `p-${Date.now().toString(36)}-${nextId++}`,
      step,
      title: title.slice(0, MAX_TITLE_CHARS),
      text: trimmed.slice(0, MAX_PLAN_COMMENT_CHARS),
    },
  ]);
}

export function removePlanComment(id: string): void {
  const current = store.getItems();
  const next = current.filter((item) => item.id !== id);
  if (next.length === current.length) return;
  store.setItems(next);
}

export function clearPlanComments(): void {
  if (!store.getItems().length) return;
  store.setItems([]);
}

export function usePlanComments(): PlanComment[] {
  return useSyncExternalStore(store.subscribe, store.getItems, store.getSnapshot);
}

/** One prose section carrying every pending plan comment, ordered as written. */
export function formatPlanCommentsMessage(comments: PlanComment[]): string {
  const lines: string[] = ["请在执行时遵守下面这些对当前计划的意见："];
  comments.forEach((comment, index) => {
    const title = comment.title.trim() ? `「${comment.title.trim()}」` : "";
    lines.push(`${index + 1}. 对计划第 ${comment.step} 步${title}：${comment.text}`);
  });
  return lines.join("\n");
}
