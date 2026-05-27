from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatIntentPolicy:
    def classify(self, question: str) -> str:
        text = question.lower()
        if self._has_any(text, self._debug_words()):
            return "debug_question"
        if self._has_any(text, self._next_step_words()):
            return "next_step_question"
        if self._has_any(text, self._status_words()):
            return "status_question"
        if self._has_any(text, self._plan_words()):
            return "plan_question"
        if self._has_any(text, self._progress_words()):
            return "progress_question"
        return "ordinary_chat"

    def _has_any(self, text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def _debug_words(self) -> list[str]:
        return [
            "debug",
            "backend",
            "run_id",
            "evidence",
            "model_route",
            "model route",
            "trace",
            "raw",
            "json",
            "调试",
            "后端",
            "证据",
            "运行id",
            "模型路由",
            "原始",
            "详细字段",
        ]

    def _next_step_words(self) -> list[str]:
        return [
            "next step",
            "next task",
            "what next",
            "what should i do",
            "need me",
            "下一步",
            "接下来",
            "下一个任务",
            "需要我",
            "执行什么",
        ]

    def _status_words(self) -> list[str]:
        return [
            "status",
            "progress",
            "current task",
            "where are we",
            "completed",
            "done",
            "blocked",
            "blocker",
            "状态",
            "进度",
            "当前任务",
            "到什么状态",
            "到哪",
            "完成了吗",
            "已完成",
            "阻塞",
            "卡住",
        ]

    def _plan_words(self) -> list[str]:
        return [
            "plan",
            "roadmap",
            "priority",
            "prioritize",
            "review plan",
            "计划",
            "路线",
            "优先级",
            "排序",
            "规划",
        ]

    def _progress_words(self) -> list[str]:
        return [
            "continue",
            "resume",
            "review",
            "accept",
            "handoff",
            "继续",
            "恢复",
            "验收",
            "评审",
            "交接",
        ]
