import React from "react";

const EXAMPLE_PROMPTS = [
  "找出并修复失败的 CI 检查",
  "加一个 --version 选项并为它写测试",
  "分析最近的失败日志,找出根因",
  "把这些笔记整理成一页 PRD",
];

export function EmptyState({ onPrompt }: { onPrompt: (text: string) => void }) {
  return (
    <section className="emptyThread">
      <h2>你想做点什么?</h2>
      <p className="emptyHint">提问、规划,或描述一个目标——涉及敏感操作前 Asteria 会先征询你。</p>
      <div className="examplePrompts">
        {EXAMPLE_PROMPTS.map((ex) => (
          <button key={ex} type="button" onClick={() => onPrompt(ex)}>{ex}</button>
        ))}
      </div>
    </section>
  );
}

