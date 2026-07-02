import type { AnyRecord, RunDetailPayload } from "../../types";

export type PlanItemState = "pending" | "in_progress" | "done" | "blocked";
export type PlanItem = { id: string; title: string; state: PlanItemState };
export type PlanModel = {
  items: PlanItem[];
  done: number;
  total: number;
  counts: { pending: number; in_progress: number; blocked: number; done: number };
};

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

function normalizeState(raw: string): PlanItemState {
  const s = raw.toLowerCase();
  if (["done", "completed", "complete", "verified", "passed", "accepted"].includes(s)) return "done";
  if (["in_progress", "in-progress", "running", "active", "current", "started"].includes(s)) return "in_progress";
  if (["blocked", "failed", "error", "needs_attention", "waiting_user", "paused"].includes(s)) return "blocked";
  return "pending";
}

// Honest plan/checklist derived from the run's real task_plan — the itemized plan the runtime
// actually executed (task_plan.tasks: {task_id, title, status}). Returns null when there is no plan
// (chat turns, or a run that emitted none) so the UI renders nothing rather than a fake shell.
export function derivePlan(runDetail: RunDetailPayload | null | undefined): PlanModel | null {
  const taskPlan = asRecord(runDetail?.task_plan);
  const rawTasks = Array.isArray(taskPlan.tasks) ? (taskPlan.tasks as unknown[]) : [];
  const items: PlanItem[] = [];
  rawTasks.forEach((task, index) => {
    const rec = asRecord(task);
    const title = String(rec.title ?? rec.content ?? "").trim();
    if (!title) return;
    const state = normalizeState(String(rec.task_status ?? rec.status ?? "pending"));
    items.push({ id: String(rec.task_id ?? rec.id ?? `task-${index}`), title, state });
  });
  if (!items.length) return null;
  const counts = { pending: 0, in_progress: 0, blocked: 0, done: 0 };
  for (const item of items) counts[item.state] += 1;
  return { items, done: counts.done, total: items.length, counts };
}

// The macro phase the run is currently in, for the phase strip. Derived from the latest event that
// carries a phase; assorted runtime phases are folded onto 5 user-facing segments.
export const MACRO_PHASES = [
  { key: "understand", label: "Understand" },
  { key: "plan", label: "Plan" },
  { key: "execute", label: "Execute" },
  { key: "review", label: "Review" },
  { key: "result", label: "Done" },
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
