// Single source for projecting internal/legacy progress-title literals to plain user language on the
// main thread (AGENTS §9 — no mechanism vocabulary up front). Shared by buildRunNarrative (the
// NarrativeStep titles the main thread renders) and userProgressTitle (runtimeNarrative). Any title
// not listed here is treated as genuine human-authored text and passes through unchanged.

export const INTERNAL_TITLE_PROJECTION: Record<string, string> = {
  "Plan/Todo": "Planning",
  "Tool Use": "Working",
  "Tool Result": "Result",
  Verify: "Checking the work",
  "Background work": "Working in the background",
  "Next step": "Next step",
  // Promotion lifecycle → plain language. The isolate→verify→merge story reads naturally from the
  // sequence ("Checking the change is safe" → "Changes applied to your workspace"), so no extra copy.
  "Promotion started": "Applying your changes",
  "Merge gate evaluated": "Checking the change is safe",
  "Candidate promoted": "Changes applied to your workspace",
  "Promotion waiting for approval": "Waiting for your approval",
  // Resume lifecycle → plain language. The "applied decisions" moment renders from its own decision
  // payload (kind=resume); these cover the surrounding start/no-op titles the runtime emits in Chinese.
  "准备恢复运行": "Resuming the session",
  "已应用恢复决策": "Resumed",
  "无需恢复": "Nothing to resume",
};

export function projectTitle(title: string): string {
  return INTERNAL_TITLE_PROJECTION[title] ?? title;
}
