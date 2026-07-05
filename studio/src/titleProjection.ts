// Single source for projecting internal/legacy progress-title literals to plain user language on the
// main thread (AGENTS §9 — no mechanism vocabulary up front). Shared by buildRunNarrative (the
// NarrativeStep titles the main thread renders) and userProgressTitle (runtimeNarrative). Any title
// not listed here is treated as genuine human-authored text and passes through unchanged.

export const INTERNAL_TITLE_PROJECTION: Record<string, string> = {
  "Plan/Todo": "规划中",
  "Tool Use": "工作中",
  "Tool Result": "结果",
  Verify: "检查工作成果",
  "Background work": "后台工作中",
  "Next step": "下一步",
  // Promotion lifecycle → plain language. The isolate→verify→merge story reads naturally from the
  // sequence ("Checking the change is safe" → "Changes applied to your workspace"), so no extra copy.
  "Promotion started": "正在应用你的改动",
  "Merge gate evaluated": "检查改动是否安全",
  "Candidate promoted": "改动已应用到你的工作区",
  "Promotion waiting for approval": "等待你的批准",
  // Resume lifecycle → plain language. The "applied decisions" moment renders from its own decision
  // payload (kind=resume); these cover the surrounding start/no-op titles the runtime emits in Chinese.
  "准备恢复运行": "正在恢复会话",
  "已应用恢复决策": "已恢复",
  "无需恢复": "无需恢复",
};

export function projectTitle(title: string): string {
  return INTERNAL_TITLE_PROJECTION[title] ?? title;
}
