from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


JUDGE_PURPOSE = "slice_completion_judge"


def build_judge_context(
    run_dir: Path,
    rule_evaluation: dict[str, Any],
    *,
    validator: SchemaValidator,
    north_star_link: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal_spec = _read_optional(run_dir, "goal_spec.json", validator, "goal_spec")
    eval_report = _read_optional(run_dir, "eval_report.json", validator, "eval_report")
    task_plan = _read_optional(run_dir, "task_plan.json", validator, "task_board")
    overall = eval_report.get("overall") if isinstance(eval_report, dict) else {}
    return {
        "run_id": rule_evaluation.get("run_id"),
        "rule_slice_complete": bool(rule_evaluation.get("slice_complete")),
        "rule_summary": str(rule_evaluation.get("summary") or ""),
        "signals": dict(rule_evaluation.get("signals") or {}),
        "north_star_milestone_id": (
            north_star_link.get("milestone_id") if north_star_link else None
        ),
        "goal": (
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "")
            if isinstance(goal_spec, dict)
            else ""
        ),
        "review_score": overall.get("score") if isinstance(overall, dict) else None,
        "review_status": overall.get("status") if isinstance(overall, dict) else None,
        "open_tasks": _open_task_titles(task_plan),
    }


def run_slice_completion_judge(
    run_dir: Path,
    rule_evaluation: dict[str, Any],
    *,
    validator: SchemaValidator,
    model_client: ModelClient | None = None,
    model_tier: str = "medium",
    north_star_link: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    policy = rule_evaluation.get("policy")
    if not isinstance(policy, dict) or not policy.get("enable_model_judge"):
        return None
    if not rule_evaluation.get("slice_complete"):
        return None

    context = build_judge_context(
        run_dir,
        rule_evaluation,
        validator=validator,
        north_star_link=north_star_link,
    )
    tier = str(policy.get("model_judge_tier") or model_tier or "medium")
    if model_client is not None:
        try:
            return _model_judge(model_client, context, tier)
        except Exception:  # noqa: BLE001
            pass
    return _deterministic_judge(context)


def apply_model_judge(
    evaluation: dict[str, Any],
    judge_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if not judge_result or judge_result.get("mode") == "skipped":
        return evaluation

    payload = dict(evaluation)
    signals = dict(payload.get("signals") or {})
    judge_complete = bool(judge_result.get("slice_complete"))
    signals["model_judge_pass"] = judge_complete
    signals["model_judge_confidence"] = judge_result.get("confidence")
    payload["signals"] = signals
    payload["model_judge"] = judge_result

    if payload.get("slice_complete") and not judge_complete:
        payload["slice_complete"] = False
        reason = str(judge_result.get("reason") or "").strip()
        payload["summary"] = (
            f"本 slice 未达成：模型判定未完成。{reason}".strip()
        )
    elif payload.get("slice_complete") and judge_complete:
        reason = str(judge_result.get("reason") or "").strip()
        if reason:
            payload["summary"] = f"本 slice 已达成完成契约。{reason}"
    return payload


def _model_judge(
    model_client: ModelClient,
    context: dict[str, Any],
    model_tier: str,
) -> dict[str, Any]:
    role_contract = role_contract_for(
        role="SliceCompletionJudge",
        purpose=JUDGE_PURPOSE,
    )
    request = ChatRequest(
        purpose=JUDGE_PURPOSE,
        model_tier=model_tier,
        messages=[
            ChatMessage(role="system", content=_system_prompt()),
            ChatMessage(role="user", content=_user_prompt(context)),
        ],
        response_format="json",
        temperature=0.1,
        max_output_tokens=800,
        metadata={
            "run_id": context.get("run_id"),
            "agent_id": "SliceCompletionJudge",
            "agent_role_contract": role_contract.to_dict(),
        },
    )
    response = model_client.chat(request)
    data = _parse_judge_json(response.content)
    return {
        "slice_complete": bool(data.get("slice_complete")),
        "confidence": float(data.get("confidence") or 0.0),
        "reason": str(data.get("reason") or ""),
        "mode": "model",
    }


def _deterministic_judge(context: dict[str, Any]) -> dict[str, Any]:
    signals = context.get("signals") if isinstance(context.get("signals"), dict) else {}
    open_tasks = context.get("open_tasks") if isinstance(context.get("open_tasks"), list) else []
    review_score = context.get("review_score")
    complete = bool(context.get("rule_slice_complete"))
    reason = "规则判定通过，确定性 judge 确认 slice 完成。"
    if open_tasks:
        complete = False
        reason = f"仍有未完成任务：{', '.join(open_tasks[:3])}。"
    elif isinstance(review_score, (int, float)) and float(review_score) < 0.75:
        complete = False
        reason = f"评审分数 {review_score} 偏低，slice 不宜标记完成。"
    return {
        "slice_complete": complete,
        "confidence": 0.7 if complete else 0.8,
        "reason": reason,
        "mode": "deterministic",
    }


def _system_prompt() -> str:
    return (
        "You judge whether a North Star slice is truly complete after accept. "
        "Return JSON only: "
        '{"slice_complete": boolean, "confidence": number 0-1, "reason": string}. '
        "Be conservative: incomplete if milestone acceptance criteria are not met."
    )


def _user_prompt(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, indent=2)


def _parse_judge_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"slice_complete": False, "confidence": 0.0, "reason": "Empty judge response."}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            return {"slice_complete": False, "confidence": 0.0, "reason": "Invalid judge JSON."}
    if not isinstance(data, dict):
        return {"slice_complete": False, "confidence": 0.0, "reason": "Judge payload not an object."}
    return data


def _read_optional(
    run_dir: Path,
    filename: str,
    validator: SchemaValidator,
    schema_name: str,
) -> dict[str, Any] | None:
    path = run_dir / filename
    if not path.exists():
        return None
    try:
        payload = JsonStore(validator).read(path, schema_name)
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _open_task_titles(task_plan: dict[str, Any] | None) -> list[str]:
    if not task_plan:
        return []
    titles: list[str] = []
    for item in task_plan.get("tasks") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        if status in {"done", "completed", "skipped"}:
            continue
        title = str(item.get("title") or item.get("task_id") or "task")
        titles.append(title)
    return titles
