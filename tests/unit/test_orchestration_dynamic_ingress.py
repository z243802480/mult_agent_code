from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_parallel_gray import (
    set_isolated_parallel_write_production_path,
    set_orchestration_dynamic_workflows_gray,
)
from asteria_runtime.core.orchestration_router import resolve_orchestration_route
from asteria_runtime.core.runtime_orchestration_catalog import build_runtime_orchestration_catalog
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _enable_dynamic_gray(tmp_path: Path, validator: SchemaValidator) -> None:
    agent_dir = tmp_path / ".asteria"
    set_isolated_parallel_write_production_path(agent_dir=agent_dir, validator=validator, enabled=True)
    set_orchestration_dynamic_workflows_gray(agent_dir=agent_dir, validator=validator, enabled=True)


def test_dynamic_orchestration_capability_blocked_by_default(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator)
    dynamic = catalog.get("run_dynamic_orchestration")
    assert dynamic is not None
    assert dynamic.available is False


def test_dynamic_orchestration_capability_when_gray(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    _enable_dynamic_gray(tmp_path, validator)
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator)
    dynamic = catalog.get("run_dynamic_orchestration")
    assert dynamic is not None
    assert dynamic.available is True
    assert dynamic.studio_mode == "orchestration"


class FakeDynamicIngressRouter:
    def __init__(self, capability_id: str) -> None:
        self.capability_id = capability_id

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=(
                f'{{"schema_version":"0.1.0","capability_id":"{self.capability_id}",'
                f'"reason":"Fake ingress eval.","confidence":"high"}}'
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-dynamic-ingress",
            raw_response={},
        )


def test_router_prefers_cold_for_small_edit_when_l3_available(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    _enable_dynamic_gray(tmp_path, validator)
    routed = resolve_orchestration_route(
        tmp_path,
        "给 greet_cli 增加 --quiet 参数并补单元测试",
        validator=validator,
        model_client=FakeDynamicIngressRouter("cold_goal_execute"),
        router_mode="model",
    )
    assert routed.capability_id == "cold_goal_execute"


def test_router_selects_dynamic_for_manifest_goal(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    _enable_dynamic_gray(tmp_path, validator)
    routed = resolve_orchestration_route(
        tmp_path,
        "用 L3 dynamic workflow manifest 跑多 phase 编排：readonly fanout、adversarial verifier、merge checkpoint，可 resume",
        validator=validator,
        model_client=FakeDynamicIngressRouter("run_dynamic_orchestration"),
        router_mode="model",
    )
    assert routed.capability_id == "run_dynamic_orchestration"
    assert routed.studio_mode == "orchestration"


def test_router_selects_cold_for_readonly_artifact_goal(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    _enable_dynamic_gray(tmp_path, validator)
    routed = resolve_orchestration_route(
        tmp_path,
        "在仓库内只读探索 orchestration 与 studio 两个目录，写一份汇总 markdown 到 docs/zh/notes/overview.md；单 session 完成，不要 L3 manifest",
        validator=validator,
        model_client=FakeDynamicIngressRouter("cold_goal_execute"),
        router_mode="model",
    )
    assert routed.capability_id == "cold_goal_execute"


def test_dynamic_ingress_gate_boundary_case_message() -> None:
    gate_path = Path.cwd() / "benchmarks" / "orchestration_dynamic_ingress_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    case = next(item for item in gate["cases"] if item["id"] == "di_not_parallel_dispatch")
    assert "markdown" in case["message"]
    assert "manifest" in case["message"].lower()


def test_router_rejects_unavailable_dynamic_capability(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)

    class BadRouter:
        def chat(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(
                content=(
                    '{"schema_version":"0.1.0","capability_id":"run_dynamic_orchestration",'
                    '"reason":"Should fail.","confidence":"high"}'
                ),
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="fake",
                model_name="fake-dynamic-ingress",
                raw_response={},
            )

    routed = resolve_orchestration_route(
        tmp_path,
        "run dynamic workflow manifest",
        validator=validator,
        model_client=BadRouter(),
        router_mode="model",
    )
    assert routed.capability_id != "run_dynamic_orchestration"
    assert routed.source in {"conservative_fallback", "rules"}
