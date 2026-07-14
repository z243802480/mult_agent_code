import React, { useState } from "react";
import { Check, ChevronRight, Circle, Loader2, TriangleAlert } from "lucide-react";
import type { PlanItemState, PlanModel } from "./planModel";

function ItemIcon({ state }: { state: PlanItemState }) {
  if (state === "done") return <Check size={13} className="planItemIcon done" />;
  if (state === "in_progress")
    return <Loader2 size={13} className="planItemIcon active spinning" />;
  if (state === "blocked") return <TriangleAlert size={13} className="planItemIcon blocked" />;
  return <Circle size={12} className="planItemIcon pending" />;
}

// Live plan/todo checklist derived from the run's real task_plan. De-boxed and compact: a "Plan · N of M"
// header that collapses the item list. Item states flip in place as the run's task_plan updates.
export function PlanChecklist({
  plan,
  defaultOpen = true,
}: {
  plan: PlanModel;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const blocked = plan.counts.blocked;
  return (
    <div className={`planChecklist ${open ? "open" : ""}`}>
      <button
        type="button"
        className="planChecklistHead"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <ChevronRight size={13} className={`chevron ${open ? "open" : ""}`} />
        <span className="planChecklistTitle">计划</span>
        <span className="planChecklistCount">
          {plan.done} / {plan.total}
          {blocked > 0 ? ` · ${blocked} 阻塞` : ""}
        </span>
      </button>
      {open && (
        <>
          {/* Why the model last re-planned (todo_write's reason). Only the model's own list carries
              this — a static task_plan never changes, so it has nothing to explain. */}
          {plan.updateReason && <p className="planReason">{plan.updateReason}</p>}
          <ol className="planItems">
            {plan.items.map((item) => (
              <li key={item.id} className={`planItem ${item.state}`}>
                <ItemIcon state={item.state} />
                <span className="planItemText">{item.title}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
