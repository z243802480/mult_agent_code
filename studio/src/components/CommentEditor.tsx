import { useState } from "react";

/**
 * The inline "write a comment" box behind 评论即指令 (G4 diff lines, G6 plan steps).
 *
 * Both surfaces had their own copy with the same keyboard contract — Ctrl/Cmd+Enter saves, Escape
 * cancels, empty text cannot be submitted. That contract is what the user learns once and expects
 * everywhere; two copies mean a fix to one leaves the other behaving differently.
 *
 * The draft lives here: a caller that owns it has to reset it on open/close, which is exactly the
 * bookkeeping the callers were each doing by hand.
 */
export function CommentEditor({
  placeholder,
  submitLabel,
  className,
  initialValue = "",
  rows = 2,
  onSave,
  onCancel,
}: {
  placeholder: string;
  submitLabel: string;
  /** Surface-specific wrapper class; actions get `${className}Actions`. */
  className: string;
  /** Seeds the draft. A comment starts blank; an EDIT starts as the thing being edited (G6 刀二). */
  initialValue?: string;
  rows?: number;
  onSave: (text: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initialValue);
  const save = () => {
    if (draft.trim()) onSave(draft);
  };
  return (
    <div className={className}>
      <textarea
        autoFocus
        value={draft}
        placeholder={placeholder}
        rows={rows}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            save();
          }
          if (event.key === "Escape") onCancel();
        }}
      />
      <div className={`${className}Actions`}>
        <button type="button" className="diffActionButton" onClick={onCancel}>
          取消
        </button>
        <button
          type="button"
          className="diffActionButton primary"
          disabled={!draft.trim()}
          onClick={save}
        >
          {submitLabel}
        </button>
      </div>
    </div>
  );
}
