import type { AnyRecord, RunDetailPayload } from "../../types";

export type PlanItemState = "pending" | "in_progress" | "done" | "blocked";
export type PlanItem = { id: string; title: string; state: PlanItemState };
export type PlanModel = {
  items: PlanItem[];
  done: number;
  total: number;
  counts: { pending: number; in_progress: number; blocked: number; done: number };
  // Where the checklist came from: the model's own todo list, or the planner's static task_plan.
  source: "model_todos" | "task_plan";
  // The model's words for why it last re-planned (todo_write's `reason`). Empty for a static plan.
  updateReason: string;
};

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

function normalizeState(raw: string): PlanItemState {
  const s = raw.toLowerCase();
  if (["done", "completed", "complete", "verified", "passed", "accepted"].includes(s))
    return "done";
  if (["in_progress", "in-progress", "running", "active", "current", "started"].includes(s))
    return "in_progress";
  if (["blocked", "failed", "error", "needs_attention", "waiting_user", "paused"].includes(s))
    return "blocked";
  return "pending";
}

function tally(
  items: PlanItem[],
  source: PlanModel["source"],
  updateReason: string,
): PlanModel | null {
  if (!items.length) return null;
  const counts = { pending: 0, in_progress: 0, blocked: 0, done: 0 };
  for (const item of items) counts[item.state] += 1;
  return { items, done: counts.done, total: items.length, counts, source, updateReason };
}

// Honest plan/checklist. Two real sources, and the model's own beats the planner's:
//   1. model_todos.json — the todo list the MODEL maintains as it works (todo_write). This is how it
//      actually organized the job, re-planning as it learned; it was written but never read here, so
//      the checklist used to show only the static plan while the model quietly worked off another one.
//   2. task_plan.json — the planner's up-front task breakdown. The fallback when the model kept no
//      todos (a short task, or a model that never called todo_write).
// Same precedence the runtime's own `todo_read` uses (model_todos → task_plan) — one source of truth,
// not a second opinion invented in the UI. Returns null when there is no plan at all (chat turns),
// so the UI renders nothing rather than a fake shell.
export function derivePlan(runDetail: RunDetailPayload | null | undefined): PlanModel | null {
  const todos = asRecord(runDetail?.model_todos);
  const rawTodos = Array.isArray(todos.items) ? (todos.items as unknown[]) : [];
  const todoItems: PlanItem[] = [];
  rawTodos.forEach((todo, index) => {
    const rec = asRecord(todo);
    const title = String(rec.content ?? rec.title ?? "").trim();
    if (!title) return;
    const state = normalizeState(String(rec.status ?? "pending"));
    todoItems.push({ id: String(rec.id ?? `todo-${index}`), title, state });
  });
  const fromTodos = tally(todoItems, "model_todos", String(todos.update_reason ?? "").trim());
  if (fromTodos) return fromTodos;

  const taskPlan = asRecord(runDetail?.task_plan);
  const rawTasks = Array.isArray(taskPlan.tasks) ? (taskPlan.tasks as unknown[]) : [];
  const items: PlanItem[] = [];
  rawTasks.forEach((task, index) => {
    const rec = asRecord(task);
    const title = String(rec.title ?? rec.content ?? "").trim();
    if (!title) return;
    const rawStatus = String(rec.task_status ?? rec.status ?? "pending").toLowerCase();
    // Superseded tasks are DEAD, not part of the live plan (F12). When auto-replan repairs a task it
    // marks the original "discarded" and adds a fresh repair task; counting the discards inflated the
    // denominator ("1/4" after the work was done, with 3 discarded repair-churn tasks). The user's
    // plan is the live tasks — the discarded lineage stays in the Inspector's task_plan evidence.
    if (rawStatus === "discarded" || rawStatus === "superseded") return;
    const state = normalizeState(rawStatus);
    items.push({ id: String(rec.task_id ?? rec.id ?? `task-${index}`), title, state });
  });
  return tally(items, "task_plan", "");
}

// The macro phase the run is currently in, for the phase strip. Derived from the latest event that
// carries a phase; assorted runtime phases are folded onto 5 user-facing segments.
export const MACRO_PHASES = [
  { key: "understand", label: "理解" },
  { key: "plan", label: "计划" },
  { key: "execute", label: "执行" },
  { key: "review", label: "查看" },
  { key: "result", label: "完成" },
] as const;

export function macroPhase(phase?: string): string {
  const p = String(phase ?? "").toLowerCase();
  if (["understand", "route", "chat"].includes(p)) return "understand";
  if (p === "plan") return "plan";
  if (["execute", "resume", "repair"].includes(p)) return "execute";
  if (p === "review") return "review";
  if (["result", "next", "final"].includes(p)) return "result";
  return "";
}
