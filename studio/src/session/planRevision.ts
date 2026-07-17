/**
 * A pending plan rewrite — G6 刀二: the user edits the plan body, the MODEL re-plans from it.
 *
 * Knife one (planComments.ts) says "对第 2 步：别动 schema" — a constraint on a step. Structural
 * changes (drop a step, add one, reorder) are miserable to write as prose, so this carries the
 * edited plan text itself. Both land in the same tray and travel the same channels; neither writes
 * a plan file. Plan revision stays a model act (ADR-0016) — the harness only delivers the words,
 * which is also why the checklist cannot lie about it: it renders the real model_todos/task_plan on
 * disk, so until the model calls todo_write, the old plan is what you see.
 *
 * Stored as a 0-or-1 list so it reuses createSessionScopedStore verbatim (session scoping, the
 * storage guards, the useSyncExternalStore contract) rather than growing a second mechanism for the
 * sake of one object.
 */

import { useSyncExternalStore } from "react";
import { createSessionScopedStore, type StorageLike } from "./sessionScopedStore";

export type PlanRevision = {
  /** The user's edited plan, one step per line. */
  text: string;
  /** The plan text as it stood when the editor opened, so we can tell edited from untouched. */
  original: string;
};

const KEY_PREFIX = "asteria.planRevision.";

export const MAX_PLAN_REVISION_CHARS = 8_000;

const store = createSessionScopedStore<PlanRevision>({ keyPrefix: KEY_PREFIX, sanitize });

export function planRevisionKey(sessionId: string): string {
  return store.key(sessionId);
}

function sanitize(items: unknown): PlanRevision[] {
  if (!Array.isArray(items)) return [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    if (typeof record.text !== "string" || !record.text.trim()) continue;
    return [
      {
        text: record.text.slice(0, MAX_PLAN_REVISION_CHARS),
        original: typeof record.original === "string" ? record.original.slice(0, MAX_PLAN_REVISION_CHARS) : "",
      },
    ];
    // Only ever one draft: there is one plan, so a second entry is corruption, not history.
  }
  return [];
}

export function loadPlanRevision(sessionId: string, storage?: StorageLike | null): PlanRevision[] {
  return store.load(sessionId, storage);
}

export function setPlanRevisionSession(sessionId: string): void {
  store.setSession(sessionId);
}

export function getPlanRevision(): PlanRevision | null {
  return store.getItems()[0] ?? null;
}

/** Stage an edited plan. An edit that matches the original is not a revision — it is a no-op. */
export function setPlanRevision(text: string, original: string): void {
  const trimmed = text.trim();
  if (!trimmed || normalize(trimmed) === normalize(original)) {
    clearPlanRevision();
    return;
  }
  store.setItems([
    { text: trimmed.slice(0, MAX_PLAN_REVISION_CHARS), original: original.slice(0, MAX_PLAN_REVISION_CHARS) },
  ]);
}

export function clearPlanRevision(): void {
  if (!store.getItems().length) return;
  store.setItems([]);
}

export function usePlanRevision(): PlanRevision | null {
  return useSyncExternalStore(store.subscribe, store.getItems, store.getSnapshot)[0] ?? null;
}

/** Compares plans ignoring cosmetic whitespace, so re-indenting a line is not "a change". */
function normalize(value: string): string {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

/** How many lines differ, for the tray summary. Positional — good enough to say "改了 N 处". */
export function countChangedLines(revision: PlanRevision): number {
  const next = normalize(revision.text).split("\n").filter(Boolean);
  const prev = normalize(revision.original).split("\n").filter(Boolean);
  let changed = Math.abs(next.length - prev.length);
  for (let i = 0; i < Math.min(next.length, prev.length); i += 1) {
    if (next[i] !== prev[i]) changed += 1;
  }
  return changed;
}

/** The plan as editable text: one step per line, no numbering (line order IS the order). */
export function planAsText(titles: string[]): string {
  return titles.map((title) => title.trim()).filter(Boolean).join("\n");
}

/**
 * The message that asks the model to re-plan. Two deliberate clauses:
 *  - "用 todo_write 更新计划": names the tool, because changing the plan must be the model's own act
 *    (ADR-0016) and todo_write is its only writer.
 *  - "不可行就先告诉我原因，不要默默跳过": keeps the model's judgement intact while ruling out the
 *    worst outcome — silently diverging from what the user asked for.
 */
export function formatPlanRevisionMessage(revision: PlanRevision): string {
  const steps = normalize(revision.text)
    .split("\n")
    .filter(Boolean)
    .map((line, index) => `${index + 1}. ${line.replace(/^\s*\d+[.、)]\s*/, "")}`);
  return [
    "下面是我改过的计划。请据此重新规划（用 todo_write 更新计划）后再继续；",
    "如果其中哪一步你认为不可行或会破坏别的东西，先告诉我原因，不要默默跳过。",
    "",
    ...steps,
  ].join("\n");
}
