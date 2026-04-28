from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionCandidate:
    question: str
    options: list[dict]
    recommended_option_id: str
    default_option_id: str
    impact: dict


class DecisionPolicy:
    """Decides when a model-suggested follow-up needs user steering."""

    _SAFETY_TERMS = {
        "privacy",
        "secret",
        "credential",
        "token",
        "network",
        "online",
        "external api",
        "deploy",
        "production",
        "destructive",
        "delete",
        "security",
        "隐私",
        "密钥",
        "凭证",
        "联网",
        "外部",
        "部署",
        "生产",
        "删除",
        "安全",
    }
    _MAJOR_TERMS = _SAFETY_TERMS | {
        "architecture",
        "tech stack",
        "framework",
        "database",
        "output medium",
        "web ui",
        "pdf",
        "scope",
        "paid",
        "budget",
        "cost",
        "架构",
        "技术栈",
        "框架",
        "数据库",
        "输出",
        "界面",
        "网页",
        "预算",
        "成本",
        "范围",
    }
    _ROUTINE_CATEGORIES = {"implementation", "bugfix", "test", "documentation", "docs"}

    def __init__(self, policy: dict) -> None:
        self.granularity = str(policy.get("decision_granularity", "balanced"))

    def candidate_for_follow_up(self, follow_up: dict) -> DecisionCandidate | None:
        if not self.should_escalate_follow_up(follow_up):
            return None
        question = str(
            follow_up.get("decision_question")
            or follow_up.get("question")
            or f"Should the agent proceed with: {self._title(follow_up)}?"
        )
        impact = self._impact(follow_up)
        options = self._options(follow_up)
        option_ids = {option["option_id"] for option in options}
        recommended = str(follow_up.get("recommended_option_id") or options[0]["option_id"])
        default = str(follow_up.get("default_option_id") or recommended)
        if recommended not in option_ids:
            recommended = options[0]["option_id"]
        if default not in option_ids:
            default = recommended
        return DecisionCandidate(
            question=question,
            options=options,
            recommended_option_id=recommended,
            default_option_id=default,
            impact=impact,
        )

    def should_escalate_follow_up(self, follow_up: dict) -> bool:
        if self.granularity == "manual":
            return True
        explicit = bool(
            follow_up.get("requires_decision")
            or follow_up.get("decision_required")
            or follow_up.get("decision_question")
        )
        impact = self._impact(follow_up)
        text = self._decision_text(follow_up)
        category = str(follow_up.get("category") or follow_up.get("type") or "").lower()
        has_high_impact = "high" in impact.values()
        has_medium_impact = "medium" in impact.values()
        safety_signal = any(term in text for term in self._SAFETY_TERMS)
        major_signal = any(term in text for term in self._MAJOR_TERMS)
        category_signal = bool(category and category not in self._ROUTINE_CATEGORIES)

        if self.granularity == "autopilot":
            return explicit and (has_high_impact or safety_signal)
        if self.granularity == "collaborative":
            return any(
                [explicit, has_medium_impact, has_high_impact, major_signal, category_signal]
            )
        return explicit or has_high_impact or major_signal or category_signal

    def _impact(self, follow_up: dict) -> dict:
        raw = follow_up.get("impact")
        if not isinstance(raw, dict):
            raw = {}
        return {
            "scope": self._impact_value(raw.get("scope") or follow_up.get("scope_impact")),
            "budget": self._impact_value(raw.get("budget") or follow_up.get("budget_impact")),
            "risk": self._impact_value(raw.get("risk") or follow_up.get("risk_impact")),
            "quality": self._impact_value(raw.get("quality") or follow_up.get("quality_impact")),
        }

    def _impact_value(self, value: object) -> str:
        value_str = str(value or "medium").lower()
        return value_str if value_str in {"low", "medium", "high"} else "medium"

    def _options(self, follow_up: dict) -> list[dict]:
        raw_options = follow_up.get("decision_options") or follow_up.get("options")
        if isinstance(raw_options, list):
            options = [
                self._option(option, index)
                for index, option in enumerate(raw_options, start=1)
            ]
            options = [option for option in options if option]
            if 2 <= len(options) <= 4:
                return options
        title = self._title(follow_up)
        return [
            {
                "option_id": "approve",
                "label": "Approve follow-up",
                "tradeoff": f"Continue with {title}; increases scope but may improve quality.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Defer",
                "tradeoff": "Keep current scope; revisit later if the goal still needs it.",
                "action": "record_constraint",
            },
        ]

    def _option(self, option: object, index: int) -> dict | None:
        if not isinstance(option, dict):
            return None
        label = str(option.get("label") or option.get("title") or "").strip()
        if not label:
            return None
        return {
            "option_id": str(option.get("option_id") or f"option-{index}"),
            "label": label,
            "tradeoff": str(option.get("tradeoff") or option.get("description") or label),
            "action": self._action(option),
        }

    def _action(self, option: dict) -> str:
        action = str(option.get("action") or "").strip()
        if action in {"create_task", "record_constraint", "cancel_scope", "require_replan"}:
            return action
        option_id = str(option.get("option_id") or "").lower()
        label = str(option.get("label") or option.get("title") or "").lower()
        if any(term in option_id or term in label for term in ["defer", "skip", "local_only"]):
            return "record_constraint"
        if any(term in option_id or term in label for term in ["cancel", "reject"]):
            return "cancel_scope"
        if "replan" in option_id or "replan" in label:
            return "require_replan"
        return "create_task"

    def _title(self, follow_up: dict) -> str:
        return str(follow_up.get("title") or follow_up.get("description") or "follow-up").strip()

    def _decision_text(self, follow_up: dict) -> str:
        values = [
            follow_up.get("title"),
            follow_up.get("description"),
            follow_up.get("decision_question"),
            follow_up.get("category"),
            follow_up.get("type"),
        ]
        return " ".join(str(value).lower() for value in values if value)
