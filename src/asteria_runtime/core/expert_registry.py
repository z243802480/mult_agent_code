"""专家注册表(MoE 骨架 · ADR-0022)。

一个"专家"不是硬编码的 agent 类,而是一份 **profile** = 人格系统提示 + 打包的方法论技能 +
模型档位 + 读写边界。主脑(跑立真身)运行时经 `spawn_subagent(role=…)` **自主选择**专家把
子任务委派出去(orchestrator-workers / MoE 路由,决策在模型)——harness 只按 profile 装配
子代理的 prompt/工具面/档位,不替模型编排拓扑(对比已删的 swarm 中央 FSM)。

这是**骨架**:一组固定的默认专家。动态 role 定义 API、与 `agent_loop_profiles` 的 capability
group 统一、以及云端隔离后端都是后续血肉(留接口,见 `docs/…/purring-fluttering-beaver` 蓝图)。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExpertProfile:
    """一个专家角色的装配契约。`methodology_skills` 用模型看到的技能工具名(如 ``skill__debug``),
    只是**前置提示**——专家子代理仍按需加载(渐进式披露);`read_only` 的专家不做写入。"""

    role: str
    persona: str  # 追加到子代理系统提示的人格/职责
    methodology_skills: tuple[str, ...] = field(default_factory=tuple)
    model_tier: str = "strong"
    read_only: bool = False


DEFAULT_EXPERTS: dict[str, ExpertProfile] = {
    "coder": ExpertProfile(
        role="coder",
        persona=(
            "You are a focused implementation expert. Make the smallest correct change that "
            "satisfies the delegated sub-task, match the surrounding style, and verify it with "
            "run_tests / run_command before you finish."
        ),
        methodology_skills=("skill__minimal-change", "skill__verify"),
        model_tier="strong",
    ),
    "diagnostic": ExpertProfile(
        role="diagnostic",
        persona=(
            "You are a debugging expert. Reproduce the failure first, find the true root cause "
            "against evidence (do not guess), then make the minimal fix and prove it is green. "
            "If you cannot confirm a cause, say so honestly."
        ),
        methodology_skills=("skill__debug", "skill__investigate"),
        model_tier="strong",
    ),
    "reviewer": ExpertProfile(
        role="reviewer",
        persona=(
            "You are a code reviewer. Check the change against the goal and the real evidence, "
            "confirm each requirement is met and verified, and flag any gap honestly. Read-only: "
            "report findings, do not edit."
        ),
        methodology_skills=("skill__retrospect", "skill__verify"),
        model_tier="strong",
        read_only=True,
    ),
    "researcher": ExpertProfile(
        role="researcher",
        persona=(
            "You are a research/investigation expert. Locate and understand the code and context "
            "relevant to the delegated question, then return an evidence-grounded summary. "
            "Read-only: search and read, do not edit."
        ),
        methodology_skills=("skill__investigate",),
        model_tier="strong",
        read_only=True,
    ),
}

_DEFAULT_ROLE = "coder"


def resolve_expert(role: str | None) -> ExpertProfile:
    """按 role 名取专家 profile;未知 role 退回默认 coder(宽容:模型偶尔给不在册的 role)。"""
    key = str(role or "").strip().lower()
    return DEFAULT_EXPERTS.get(key, DEFAULT_EXPERTS[_DEFAULT_ROLE])


def expert_roles() -> list[str]:
    """已注册的专家 role 名(供 spawn_subagent 的提示告诉模型可选哪些专家)。"""
    return list(DEFAULT_EXPERTS)
