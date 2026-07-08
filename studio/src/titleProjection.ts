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
  // Execution-narrative titles the runtime still emits in English (instrumentation literals). Evidence
  // stays English at source (asserted by tests); this projects them to plain Chinese on the surface.
  Thinking: "思考中",
  Drafting: "正在草拟",
  "Draft complete": "草拟完成",
  "Worker action requested": "请求执行动作",
  "Worker action proposed": "已提出执行动作",
  "Agent loop dispatch loaded": "已载入执行环境",
  "Agent loop profiles selected": "已选择执行档",
  "Agent loop profiles for planned tasks": "已为计划任务选择执行档",
  "Workspace selected": "已选定工作区",
  "Workspace and outputs selected": "已选定工作区与输出",
  "Build task plan": "构建任务计划",
  "Task plan built": "任务计划已构建",
  "Evaluate task plan": "评估任务计划",
  "Task plan evaluated": "任务计划已评估",
  "Task plan evaluation written": "已写出计划评估",
  "Task plan files written": "已写出计划文件",
  "GoalSpec file written": "已写出目标规格",
  "Permission mode selected": "已选择权限模式",
  "Capability decision recorded": "已记录能力决策",
  "Model route decision": "模型路由决策",
  "Model connection interrupted": "模型连接中断",
  "Candidate workspace created": "已创建隔离候选工作区",
  "Completion contract checked": "已核对完成契约",
  "Task execution evidence recorded": "已记录任务执行证据",
  "File changes captured": "已捕获文件改动",
  "File changes recorded": "已记录文件改动",
  "Validation conclusion": "验证结论",
  "Validation results recorded": "已记录验证结果",
  "Cost report written": "已写出成本报告",
  "Final report written": "已写出最终报告",
};

export function projectTitle(title: string): string {
  return INTERNAL_TITLE_PROJECTION[title] ?? title;
}

// Dynamic summary literals the runtime emits in English (they carry ids/counts, so a static map can't
// catch them). Kept here beside the title map so the surface has one localization source. Evidence
// stays English at source (asserted by tests); this only rewrites the human-facing summary line.
const SUMMARY_PROJECTIONS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^(\S+) completed with verified evidence\.?$/, (m) => `${m[1]} 已完成，证据已通过验证。`],
  [/^Created (\d+) task\(s\) from the GoalSpec\.?$/, (m) => `已从目标规格生成 ${m[1]} 个任务。`],
  [/^(\d+) changed file\(s\) are now visible in the run timeline\.?$/, (m) => `${m[1]} 个改动文件已在运行时间线中可见。`],
  [/^Validation passed: (\d+)\/(\d+) check\(s\) passed\.?$/, (m) => `验证通过：${m[1]}/${m[2]} 项检查已通过。`],
  [/^All (\d+) verification command\(s\) passed and no tasks are blocked\.?$/, (m) => `全部 ${m[1]} 条验证命令通过，无任务受阻。`],
  // Internal task ids (task-000N) must never surface on the main thread — the user thinks in the
  // work, not the runtime's bookkeeping counter. These phrasings all carried a raw id; rewrite them
  // to plain language that drops it.
  [/^Asked the coder model to propose execution steps for \S+\.?$/, () => `已请编码模型规划下一步执行步骤。`],
  [/^task-\S+ 已被 task-\S+ 替代并进入后续执行。?$/, () => `当前任务已被新的修复任务替代，继续执行。`],
  [/^Tool is not allowed for \S+: (.+)$/, (m) => `当前任务不允许使用该工具：${m[1]}`],
  [/^Updated (\S+)$/, (m) => `已更新 ${m[1]}`],
  [/^Wrote file: (\S+)$/, (m) => `已写入文件：${m[1]}`],
  [/^Running (.+)$/, (m) => `正在运行 ${m[1]}`],
];

export function projectSummary(summary: string): string {
  const trimmed = summary.trim();
  for (const [pattern, render] of SUMMARY_PROJECTIONS) {
    const match = trimmed.match(pattern);
    if (match) return render(match);
  }
  // Safety net: any unlisted phrasing that still embeds a raw task id gets the id neutralized rather
  // than leaked verbatim to the user (e.g. "…task-0007…" → "…任务…").
  return trimmed.replace(/\btask-\d+\b/g, "任务");
}
