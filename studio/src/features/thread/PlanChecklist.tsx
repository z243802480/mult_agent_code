import React, { useState } from "react";
import { CommentEditor } from "../../components/CommentEditor";
import {
  Check,
  ChevronRight,
  Circle,
  Loader2,
  MessageSquarePlus,
  TriangleAlert,
  X,
} from "lucide-react";
import type { PlanItemState, PlanModel } from "./planModel";
import { addPlanComment, removePlanComment, usePlanComments } from "../../session/planComments";

function ItemIcon({ state }: { state: PlanItemState }) {
  if (state === "done") return <Check size={13} className="planItemIcon done" />;
  if (state === "in_progress")
    return <Loader2 size={13} className="planItemIcon active spinning" />;
  if (state === "blocked") return <TriangleAlert size={13} className="planItemIcon blocked" />;
  return <Circle size={12} className="planItemIcon pending" />;
}

// Live plan/todo checklist derived from the run's real task_plan. De-boxed and compact: a "Plan · N of M"
// header that collapses the item list. Item states flip in place as the run's task_plan updates.
// G6 刀一: each step carries a comment entry — "对计划第 N 步的意见" accumulates in the shared
// pending-feedback tray and reaches the model as one batched message (Jules/VS Code plan-comment
// semantics; plan revision itself stays a model act, we only deliver the user's words).
export function PlanChecklist({
  plan,
  defaultOpen = true,
}: {
  plan: PlanModel;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [editorAt, setEditorAt] = useState<number | null>(null);
  const comments = usePlanComments();
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
            {plan.items.map((item, index) => {
              const step = index + 1;
              const stepComments = comments.filter((comment) => comment.step === step);
              return (
                <li key={item.id} className={`planItem ${item.state}`}>
                  <div className="planItemRow">
                    <ItemIcon state={item.state} />
                    <span className="planItemText">{item.title}</span>
                    <button
                      type="button"
                      className="planItemComment"
                      title="对这一步写意见"
                      aria-label={`对计划第 ${step} 步写意见`}
                      onClick={() => setEditorAt(editorAt === index ? null : index)}
                    >
                      <MessageSquarePlus size={12} />
                    </button>
                  </div>
                  {stepComments.map((comment) => (
                    <div key={comment.id} className="planCommentCard">
                      <span className="planCommentText">{comment.text}</span>
                      <button
                        type="button"
                        className="diffCommentRemove"
                        title="删除这条意见"
                        aria-label="删除这条计划意见"
                        onClick={() => removePlanComment(comment.id)}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                  {editorAt === index && (
                    <CommentEditor
                      className="planCommentEditor"
                      placeholder="对这一步写意见…（Ctrl+Enter 保存）"
                      submitLabel="添加意见"
                      onSave={(text: string) => {
                        addPlanComment(step, item.title, text);
                        setEditorAt(null);
                      }}
                      onCancel={() => setEditorAt(null)}
                    />
                  )}
                </li>
              );
            })}
          </ol>
        </>
      )}
    </div>
  );
}
