import React, { useEffect, useState } from "react";
import { BookOpen, ChevronRight } from "lucide-react";
import { api } from "../../api";

// G14 记忆管理 UI（只读起步）— render the runtime's long-task memory (.asteria/memory/active_goal)
// exactly as recorded: the structured JSON is the authoritative source (what the loop actually
// feeds back to the doer, ADR-0024), the markdown原文 is the human-readable mirror. READ-ONLY by
// design: what deserves remembering is currently a harness act (deterministic extraction), and an
// edit surface would promise write semantics the runtime does not have — that fork is a recorded
// DecisionPoint, not something to fake in the UI.

export type ActiveGoalMemoryView = {
  currentGoal: string;
  updatedAt: string;
  updatedBy: string;
  sourceRunId: string;
  resultState: string;
  plan: { title: string; status: string }[];
  completedWork: string[];
  nextTask: string[];
  blockers: string[];
  watchItems: string[];
};

function stringList(value: unknown, cap = 12): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) =>
      String(item ?? "")
        .replace(/^-\s*/, "")
        .trim(),
    )
    .filter(Boolean)
    .slice(0, cap);
}

/** Tolerant projection of active_goal.json — corrupt/missing input yields null, never a throw. */
export function parseActiveGoalMemory(raw: string): ActiveGoalMemoryView | null {
  let data: Record<string, unknown>;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    data = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  const result = (data.current_result ?? {}) as Record<string, unknown>;
  const plan = Array.isArray(data.overall_plan)
    ? (data.overall_plan as Record<string, unknown>[])
        .map((task) => ({
          title: String(task?.title ?? "").trim(),
          status: String(task?.status ?? "").trim(),
        }))
        .filter((task) => task.title)
        .slice(0, 12)
    : [];
  return {
    currentGoal: String(data.current_goal ?? "").trim(),
    updatedAt: String(data.updated_at ?? "").trim(),
    updatedBy: String(data.updated_by ?? "").trim(),
    sourceRunId: String(data.source_run_id ?? "").trim(),
    resultState: String(result.state ?? "").trim(),
    plan,
    completedWork: stringList(data.completed_work),
    nextTask: stringList(data.next_task, 6),
    blockers: stringList(data.current_blockers, 6),
    watchItems: stringList(data.watch_items, 6),
  };
}

const RESULT_LABEL: Record<string, string> = {
  accepted: "已接受",
  completed: "已完成",
  blocked: "受阻",
  in_progress: "进行中",
};

export function MemoryPanel() {
  const [memory, setMemory] = useState<ActiveGoalMemoryView | null>(null);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([
      api.previewFile(".asteria/memory/active_goal.json").catch(() => null),
      api.previewFile(".asteria/memory/active_goal.md").catch(() => null),
    ])
      .then(([json, md]) => {
        if (!alive) return;
        setMemory(json?.ok && json.content ? parseActiveGoalMemory(json.content) : null);
        setMarkdown(md?.ok && md.content ? md.content : null);
      })
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (!loaded) return <p className="muted">读取长任务记忆…</p>;
  if (!memory) {
    return (
      <div className="memoryPanel empty">
        <BookOpen size={20} />
        <p>这个工作区还没有长任务记忆。</p>
        <small>
          active_goal
          记忆由运行时在目标推进过程中自动记录（完成了什么、产出了哪些文件、下一步是什么），供后续运行读回，避免重做已完成的工作。
        </small>
      </div>
    );
  }

  return (
    <div className="memoryPanel">
      <div className="memoryMeta">
        <small>
          记录于 {memory.updatedAt || "未知时间"}
          {memory.sourceRunId ? ` · ${memory.sourceRunId}` : ""}
          {memory.updatedBy ? ` · 由 ${memory.updatedBy} 更新` : ""} · 只读（记忆由运行时自动维护）
        </small>
      </div>
      <section className="memoryBlock">
        <h3>当前目标</h3>
        <p>{memory.currentGoal || "（未记录）"}</p>
        {memory.resultState && (
          <span className={`memoryState state-${memory.resultState}`}>
            {RESULT_LABEL[memory.resultState] ?? memory.resultState}
          </span>
        )}
      </section>
      {memory.plan.length > 0 && (
        <section className="memoryBlock">
          <h3>总体计划</h3>
          <ul>
            {memory.plan.map((task, index) => (
              <li key={`${index}-${task.title.slice(0, 12)}`}>
                <span className={`memoryTaskStatus status-${task.status}`}>
                  {task.status === "done" ? "✓" : task.status === "blocked" ? "⚠" : "·"}
                </span>
                {task.title}
              </li>
            ))}
          </ul>
        </section>
      )}
      {memory.completedWork.length > 0 && (
        <section className="memoryBlock">
          <h3>已完成</h3>
          <ul>
            {memory.completedWork.map((item, index) => (
              <li key={`done-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {memory.blockers.length > 0 && (
        <section className="memoryBlock warn">
          <h3>当前阻塞</h3>
          <ul>
            {memory.blockers.map((item, index) => (
              <li key={`blk-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {memory.nextTask.length > 0 && (
        <section className="memoryBlock">
          <h3>下一步</h3>
          <ul>
            {memory.nextTask.map((item, index) => (
              <li key={`next-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {memory.watchItems.length > 0 && (
        <section className="memoryBlock">
          <h3>观察项</h3>
          <ul>
            {memory.watchItems.map((item, index) => (
              <li key={`watch-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {markdown && (
        <div className="memoryRaw">
          <button
            type="button"
            className="memoryRawToggle"
            onClick={() => setRawOpen(!rawOpen)}
            aria-expanded={rawOpen}
          >
            <ChevronRight size={12} className={`chevron ${rawOpen ? "open" : ""}`} />
            记忆原文（active_goal.md）
          </button>
          {rawOpen && <pre className="memoryRawBody">{markdown.slice(0, 20000)}</pre>}
        </div>
      )}
    </div>
  );
}
