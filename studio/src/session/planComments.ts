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

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function storage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function planCommentsKey(sessionId: string): string {
  return `${KEY_PREFIX}${sessionId}`;
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

export function loadPlanComments(
  sessionId: string,
  store: StorageLike | null = storage(),
): PlanComment[] {
  if (!sessionId || !store) return [];
  try {
    const raw = store.getItem(planCommentsKey(sessionId));
    if (!raw) return [];
    return sanitize(JSON.parse(raw));
  } catch {
    return [];
  }
}

export function savePlanComments(
  sessionId: string,
  comments: PlanComment[],
  store: StorageLike | null = storage(),
): void {
  if (!sessionId || !store) return;
  try {
    if (!comments.length) {
      store.removeItem(planCommentsKey(sessionId));
      return;
    }
    store.setItem(planCommentsKey(sessionId), JSON.stringify(sanitize(comments)));
  } catch {
    // Persistence is best-effort; the in-memory list keeps working.
  }
}

// Module store — one active session at a time, same rationale as diffComments.
let activeSessionId = "";
let current: PlanComment[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function setPlanCommentSession(sessionId: string): void {
  if (sessionId === activeSessionId) return;
  activeSessionId = sessionId;
  current = loadPlanComments(sessionId);
  emit();
}

export function getPlanComments(): PlanComment[] {
  return current;
}

let nextId = 1;

export function addPlanComment(step: number, title: string, text: string): void {
  const trimmed = text.trim();
  if (!trimmed || step < 1 || current.length >= MAX_PLAN_COMMENTS) return;
  current = [
    ...current,
    {
      id: `p-${Date.now().toString(36)}-${nextId++}`,
      step,
      title: title.slice(0, MAX_TITLE_CHARS),
      text: trimmed.slice(0, MAX_PLAN_COMMENT_CHARS),
    },
  ];
  savePlanComments(activeSessionId, current);
  emit();
}

export function removePlanComment(id: string): void {
  const next = current.filter((item) => item.id !== id);
  if (next.length === current.length) return;
  current = next;
  savePlanComments(activeSessionId, current);
  emit();
}

export function clearPlanComments(): void {
  if (!current.length) return;
  current = [];
  savePlanComments(activeSessionId, current);
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePlanComments(): PlanComment[] {
  return useSyncExternalStore(subscribe, getPlanComments, () => current);
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
