import React, { useState } from "react";
import { CommentEditor } from "../../components/CommentEditor";
import {
  Check,
  ChevronRight,
  Circle,
  Loader2,
  MessageSquarePlus,
  Pencil,
  TriangleAlert,
  X,
} from "lucide-react";
import type { PlanItemState, PlanModel } from "./planModel";
import { addPlanComment, removePlanComment, usePlanComments } from "../../session/planComments";
import { planAsText, setPlanRevision, usePlanRevision } from "../../session/planRevision";

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
// G6 刀二: the plan body itself is editable — structural changes (drop/add/reorder a step) are
// miserable to write as prose. The edited text lands in the same tray and asks the model to re-plan
// from it. Note what is NOT here: no write to model_todos/task_plan, and no optimistic render of
// the edit. The list below always shows the plan that is actually on disk, so if the model declines
// the rewrite, nothing here ever claimed otherwise.
export function PlanChecklist({
  plan,
  defaultOpen = true,
}: {
  plan: PlanModel;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [editorAt, setEditorAt] = useState<number | null>(null);
  const [editingPlan, setEditingPlan] = useState(false);
  const comments = usePlanComments();
  const revision = usePlanRevision();
  const blocked = plan.counts.blocked;
  const planText = planAsText(plan.items.map((item) => item.title));

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
          <div className="planChecklistActions">
            <button
              type="button"
              className="planEditButton"
              aria-expanded={editingPlan}
              onClick={() => setEditingPlan((editing) => !editing)}
            >
              <Pencil size={12} /> 编辑计划
            </button>
            {revision && <span className="planRevisionPending muted">改过的计划待提交</span>}
          </div>
          {editingPlan && (
            <CommentEditor
              className="planRevisionEditor"
              // Prefilled with the plan as it stands, so editing is editing — not retyping.
              initialValue={revision?.text ?? planText}
              rows={Math.min(Math.max(plan.items.length + 1, 3), 12)}
              placeholder="一行一步，改完提交给模型重新规划…（Ctrl+Enter 保存）"
              submitLabel="加入待提交"
              onSave={(text: string) => {
                // `planText` (not the draft) is the baseline: an edit that lands back on the real
                // plan is not a revision, and setPlanRevision drops it rather than asking the model
                // to re-plan into what it already has.
                setPlanRevision(text, planText);
                setEditingPlan(false);
              }}
              onCancel={() => setEditingPlan(false)}
            />
          )}
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
