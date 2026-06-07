from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.route_command import RouteCommand
from asteria_runtime.core.orchestration_route_recorder import orchestration_routes_path
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_route_command_records_orchestration_evidence(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    RouteCommand(
        tmp_path,
        "Python 里 list 和 tuple 有什么区别？",
        use_model=False,
        router_mode_override="rules",
    ).run()
    path = orchestration_routes_path(tmp_path / ".asteria")
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    assert "chat_answer" in lines[-1]
    assert "rules" in lines[-1]
