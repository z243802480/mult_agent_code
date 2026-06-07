from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.orchestration_parallel_gray import (
    build_orchestration_parallel_decision_point,
    evaluate_orchestration_parallel_readiness,
)


def _write_spawn_evidence(path: Path, *, hit_rate: float, case_count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "real",
                "summary": {"hit_rate": hit_rate, "case_count": case_count},
            }
        ),
        encoding="utf-8",
    )


def _write_route_evidence(path: Path, *, hit_rate: float, case_count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "model",
                "summary": {"hit_rate": hit_rate, "case_count": case_count},
            }
        ),
        encoding="utf-8",
    )


def test_readiness_passes_with_eval_evidence(tmp_path: Path) -> None:
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    spawn = tmp_path / "spawn.json"
    route = tmp_path / "route.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)

    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
    )
    assert readiness.ready_for_decision_point is True
    assert readiness.ready_for_maintainer_probe is False


def test_readiness_requires_gray_drill_for_probe(tmp_path: Path) -> None:
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")
    spawn = tmp_path / "spawn.json"
    route = tmp_path / "route.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)

    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    assert readiness.ready_for_maintainer_probe is True


def test_decision_point_defaults_to_defer_without_drill(tmp_path: Path) -> None:
    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=tmp_path / "missing.json",
        route_evidence_path=tmp_path / "missing2.json",
    )
    decision = build_orchestration_parallel_decision_point(
        run_id="run-test",
        readiness=readiness,
    )
    assert decision["default_option_id"] == "defer"
    assert decision["recommended_option_id"] == "defer"


def test_wave2_band_resolves_decision_and_runs_gray(tmp_path: Path) -> None:
    from asteria_runtime.core.orchestration_parallel_gray import (
        build_orchestration_parallel_decision_point,
        resolve_orchestration_parallel_decision,
        run_orchestration_wave2_band,
    )
    from asteria_runtime.storage.schema_validator import SchemaValidator

    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    verification = tmp_path / ".asteria" / "verification"
    verification.mkdir(parents=True)
    spawn = verification / "orchestration_spawn_real_20260607.json"
    route = verification / "orchestration_route_real_20260607.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)

    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    decision = build_orchestration_parallel_decision_point(
        run_id="run-test",
        readiness=readiness,
    )
    decisions_dir = tmp_path / ".asteria" / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "decision-orchestration-parallel-0001.json").write_text(
        json.dumps(decision, ensure_ascii=False),
        encoding="utf-8",
    )

    validator = SchemaValidator(Path.cwd() / "schemas")
    result = run_orchestration_wave2_band(
        repo_root=tmp_path,
        validator=validator,
    )
    assert result.ok is True
    assert result.decision["status"] == "resolved"
    assert result.decision["selected_option_id"] == "wave2_maintainer_probe"
    assert result.evidence_path is not None
    assert result.evidence_path.exists()

    resolved = resolve_orchestration_parallel_decision(
        agent_dir=tmp_path / ".asteria",
        validator=validator,
        decision_id="decision-orchestration-parallel-0001",
        selected_option_id="wave2_maintainer_probe",
    )
    assert resolved["status"] == "resolved"


def _write_wave2_evidence(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"ok": True, "wave": 2, "selected_option_id": "wave2_maintainer_probe"}),
        encoding="utf-8",
    )


def test_wave3_readiness_requires_wave2(tmp_path: Path) -> None:
    from asteria_runtime.core.orchestration_parallel_gray import evaluate_wave3_catalog_readiness

    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")
    readiness = evaluate_wave3_catalog_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
    )
    assert readiness.ready_for_catalog_probe is False
    assert "wave2_probe_missing_or_failed" in readiness.blockers


def test_wave3_catalog_probe_enables_gray(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.orchestration_parallel_gray import (
        build_orchestration_parallel_decision_point,
        evaluate_orchestration_parallel_readiness,
        evaluate_wave3_catalog_readiness,
        run_orchestration_wave3_catalog_probe,
    )
    from asteria_runtime.core.runtime_orchestration_catalog import build_runtime_orchestration_catalog
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True, exist_ok=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    verification = tmp_path / ".asteria" / "verification"
    verification.mkdir(parents=True)
    spawn = verification / "orchestration_spawn_real_20260607.json"
    route = verification / "orchestration_route_real_20260607.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)
    _write_wave2_evidence(verification / "orchestration_wave2_probe.json")

    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    wave2_decision = build_orchestration_parallel_decision_point(
        run_id="run-test",
        readiness=readiness,
    )
    wave2_decision["status"] = "resolved"
    wave2_decision["selected_option_id"] = "wave2_maintainer_probe"
    wave2_decision["resolved_at"] = "2026-06-07T00:00:00+08:00"
    decisions_dir = tmp_path / ".asteria" / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "decision-orchestration-parallel-0001.json").write_text(
        json.dumps(wave2_decision, ensure_ascii=False),
        encoding="utf-8",
    )

    validator = SchemaValidator(Path.cwd() / "schemas")
    w3_readiness = evaluate_wave3_catalog_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
    )
    assert w3_readiness.ready_for_catalog_probe is True

    result = run_orchestration_wave3_catalog_probe(repo_root=tmp_path, validator=validator)
    assert result.ok is True
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator)
    assert catalog.get("spawn_parallel_workers").available is True


def test_wave4_readiness_requires_wave3_catalog(tmp_path: Path) -> None:
    from asteria_runtime.core.orchestration_parallel_gray import evaluate_wave4_workflows_readiness

    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")
    readiness = evaluate_wave4_workflows_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
    )
    assert readiness.ready_for_workflows_probe is False
    assert "wave3_probe_missing_or_failed" in readiness.blockers


def test_wave4_workflows_probe_enables_gray(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.orchestration_parallel_gray import (
        CATALOG_GRAY_POLICY_KEY,
        WORKFLOWS_GRAY_POLICY_KEY,
        build_orchestration_parallel_decision_point,
        build_wave3_catalog_decision_point,
        evaluate_orchestration_parallel_readiness,
        evaluate_wave3_catalog_readiness,
        evaluate_wave4_workflows_readiness,
        run_orchestration_wave4_workflows_probe,
        set_spawn_parallel_workers_catalog_gray,
    )
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True, exist_ok=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    verification = tmp_path / ".asteria" / "verification"
    verification.mkdir(parents=True)
    spawn = verification / "orchestration_spawn_real_20260607.json"
    route = verification / "orchestration_route_real_20260607.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)
    _write_wave2_evidence(verification / "orchestration_wave2_probe.json")

    validator = SchemaValidator(Path.cwd() / "schemas")
    readiness_w2 = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    wave2_decision = build_orchestration_parallel_decision_point(
        run_id="run-test",
        readiness=readiness_w2,
    )
    wave2_decision["status"] = "resolved"
    wave2_decision["selected_option_id"] = "wave2_maintainer_probe"
    wave2_decision["resolved_at"] = "2026-06-07T00:00:00+08:00"
    decisions_dir = tmp_path / ".asteria" / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "decision-orchestration-parallel-0001.json").write_text(
        json.dumps(wave2_decision, ensure_ascii=False),
        encoding="utf-8",
    )

    w3_readiness = evaluate_wave3_catalog_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
    )
    wave3_decision = build_wave3_catalog_decision_point(run_id="run-test", readiness=w3_readiness)
    wave3_decision["status"] = "resolved"
    wave3_decision["selected_option_id"] = "wave3_catalog_gray"
    wave3_decision["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0002.json").write_text(
        json.dumps(wave3_decision, ensure_ascii=False),
        encoding="utf-8",
    )
    (verification / "orchestration_wave3_catalog_probe.json").write_text(
        json.dumps({"ok": True, "wave": 3}),
        encoding="utf-8",
    )
    set_spawn_parallel_workers_catalog_gray(
        agent_dir=tmp_path / ".asteria",
        validator=validator,
        enabled=True,
    )

    w4_readiness = evaluate_wave4_workflows_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
    )
    assert w4_readiness.ready_for_workflows_probe is True

    result = run_orchestration_wave4_workflows_probe(repo_root=tmp_path, validator=validator)
    assert result.ok is True
    policy = load_policy_config(tmp_path / ".asteria", validator)
    agent_loop = policy.get("agent_loop") or {}
    assert agent_loop.get(CATALOG_GRAY_POLICY_KEY) is True
    assert agent_loop.get(WORKFLOWS_GRAY_POLICY_KEY) is True
    assert agent_loop.get("parallel_writes") is not True


def test_wave5_production_path_probe_enables_explicit_path(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.orchestration_parallel_gray import (
        PRODUCTION_PATH_POLICY_KEY,
        build_orchestration_parallel_decision_point,
        build_wave3_catalog_decision_point,
        build_wave4_workflows_decision_point,
        evaluate_orchestration_parallel_readiness,
        evaluate_wave3_catalog_readiness,
        evaluate_wave4_workflows_readiness,
        evaluate_wave5_production_path_readiness,
        run_orchestration_wave5_production_path_probe,
        set_orchestration_workflows_gray,
        set_spawn_parallel_workers_catalog_gray,
    )
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True, exist_ok=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    verification = tmp_path / ".asteria" / "verification"
    verification.mkdir(parents=True)
    spawn = verification / "orchestration_spawn_real_20260607.json"
    route = verification / "orchestration_route_real_20260607.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)
    _write_wave2_evidence(verification / "orchestration_wave2_probe.json")

    validator = SchemaValidator(Path.cwd() / "schemas")
    readiness_w2 = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    decisions_dir = tmp_path / ".asteria" / "decisions"
    decisions_dir.mkdir(parents=True)

    for decision_id, builder, readiness_obj, option in (
        (
            "decision-orchestration-parallel-0001",
            build_orchestration_parallel_decision_point,
            readiness_w2,
            "wave2_maintainer_probe",
        ),
    ):
        d = builder(run_id="run-test", readiness=readiness_obj)
        d["status"] = "resolved"
        d["selected_option_id"] = option
        d["resolved_at"] = "2026-06-07T00:00:00+08:00"
        (decisions_dir / f"{decision_id}.json").write_text(json.dumps(d), encoding="utf-8")

    w3_readiness = evaluate_wave3_catalog_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
    )
    w3 = build_wave3_catalog_decision_point(run_id="run-test", readiness=w3_readiness)
    w3["status"] = "resolved"
    w3["selected_option_id"] = "wave3_catalog_gray"
    w3["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0002.json").write_text(
        json.dumps(w3), encoding="utf-8"
    )
    (verification / "orchestration_wave3_catalog_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_spawn_parallel_workers_catalog_gray(
        agent_dir=tmp_path / ".asteria", validator=validator, enabled=True
    )

    w4_readiness = evaluate_wave4_workflows_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
    )
    w4 = build_wave4_workflows_decision_point(run_id="run-test", readiness=w4_readiness)
    w4["status"] = "resolved"
    w4["selected_option_id"] = "wave4_workflows_gray"
    w4["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0003.json").write_text(
        json.dumps(w4), encoding="utf-8"
    )
    (verification / "orchestration_wave4_workflows_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_orchestration_workflows_gray(agent_dir=tmp_path / ".asteria", validator=validator, enabled=True)

    w5_readiness = evaluate_wave5_production_path_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
        wave4_evidence_path=verification / "orchestration_wave4_workflows_probe.json",
    )
    assert w5_readiness.ready_for_production_probe is True

    result = run_orchestration_wave5_production_path_probe(repo_root=tmp_path, validator=validator)
    assert result.ok is True
    policy = load_policy_config(tmp_path / ".asteria", validator)
    agent_loop = policy.get("agent_loop") or {}
    assert agent_loop.get(PRODUCTION_PATH_POLICY_KEY) is True
    assert agent_loop.get("parallel_writes") is not True
    assert result.validation_run_path is not None
    assert result.validation_run_path.exists()


def test_wave6_dynamic_probe_enables_l3_gray(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.orchestration_parallel_gray import (
        DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY,
        PRODUCTION_PATH_POLICY_KEY,
        build_orchestration_parallel_decision_point,
        build_wave3_catalog_decision_point,
        build_wave4_workflows_decision_point,
        build_wave5_production_path_decision_point,
        evaluate_orchestration_parallel_readiness,
        evaluate_wave3_catalog_readiness,
        evaluate_wave4_workflows_readiness,
        evaluate_wave5_production_path_readiness,
        evaluate_wave6_dynamic_readiness,
        run_orchestration_wave6_dynamic_probe,
        set_isolated_parallel_write_production_path,
        set_orchestration_workflows_gray,
        set_spawn_parallel_workers_catalog_gray,
    )
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True, exist_ok=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    verification = tmp_path / ".asteria" / "verification"
    verification.mkdir(parents=True)
    spawn = verification / "orchestration_spawn_real_20260607.json"
    route = verification / "orchestration_route_real_20260607.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)
    _write_wave2_evidence(verification / "orchestration_wave2_probe.json")

    validator = SchemaValidator(Path.cwd() / "schemas")
    readiness_w2 = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    decisions_dir = tmp_path / ".asteria" / "decisions"
    decisions_dir.mkdir(parents=True)

    w2 = build_orchestration_parallel_decision_point(run_id="run-test", readiness=readiness_w2)
    w2["status"] = "resolved"
    w2["selected_option_id"] = "wave2_maintainer_probe"
    w2["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0001.json").write_text(
        json.dumps(w2), encoding="utf-8"
    )

    w3_readiness = evaluate_wave3_catalog_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
    )
    w3 = build_wave3_catalog_decision_point(run_id="run-test", readiness=w3_readiness)
    w3["status"] = "resolved"
    w3["selected_option_id"] = "wave3_catalog_gray"
    w3["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0002.json").write_text(
        json.dumps(w3), encoding="utf-8"
    )
    (verification / "orchestration_wave3_catalog_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_spawn_parallel_workers_catalog_gray(
        agent_dir=tmp_path / ".asteria", validator=validator, enabled=True
    )

    w4_readiness = evaluate_wave4_workflows_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
    )
    w4 = build_wave4_workflows_decision_point(run_id="run-test", readiness=w4_readiness)
    w4["status"] = "resolved"
    w4["selected_option_id"] = "wave4_workflows_gray"
    w4["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0003.json").write_text(
        json.dumps(w4), encoding="utf-8"
    )
    (verification / "orchestration_wave4_workflows_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_orchestration_workflows_gray(agent_dir=tmp_path / ".asteria", validator=validator, enabled=True)

    w5_readiness = evaluate_wave5_production_path_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
        wave4_evidence_path=verification / "orchestration_wave4_workflows_probe.json",
    )
    w5 = build_wave5_production_path_decision_point(run_id="run-test", readiness=w5_readiness)
    w5["status"] = "resolved"
    w5["selected_option_id"] = "wave5_isolated_production_path"
    w5["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0004.json").write_text(
        json.dumps(w5), encoding="utf-8"
    )
    (verification / "orchestration_wave5_production_path.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_isolated_parallel_write_production_path(
        agent_dir=tmp_path / ".asteria", validator=validator, enabled=True
    )

    gate_src = Path.cwd() / "benchmarks" / "orchestration_wave6_dynamic_gate.json"
    manifest_src = Path.cwd() / "benchmarks" / "orchestration_wave6_dynamic_manifest.json"
    bench = tmp_path / "benchmarks"
    bench.mkdir(parents=True)
    bench.joinpath("orchestration_wave6_dynamic_gate.json").write_text(
        gate_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    bench.joinpath("orchestration_wave6_dynamic_manifest.json").write_text(
        manifest_src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    w6_readiness = evaluate_wave6_dynamic_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
        wave4_evidence_path=verification / "orchestration_wave4_workflows_probe.json",
        wave5_evidence_path=verification / "orchestration_wave5_production_path.json",
    )
    assert w6_readiness.ready_for_dynamic_probe is True

    result = run_orchestration_wave6_dynamic_probe(repo_root=tmp_path, validator=validator)
    assert result.ok is True
    policy = load_policy_config(tmp_path / ".asteria", validator)
    agent_loop = policy.get("agent_loop") or {}
    assert agent_loop.get(DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY) is True
    assert agent_loop.get(PRODUCTION_PATH_POLICY_KEY) is True
    assert agent_loop.get("parallel_writes") is not True
    assert agent_loop.get("max_parallel_workers_per_run") == 16


def test_wave7_live_probe_enables_execution_gray(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.orchestration_parallel_gray import (
        DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY,
        LIVE_EXECUTION_GRAY_POLICY_KEY,
        PRODUCTION_PATH_POLICY_KEY,
        build_orchestration_parallel_decision_point,
        build_wave3_catalog_decision_point,
        build_wave4_workflows_decision_point,
        build_wave5_production_path_decision_point,
        build_wave6_dynamic_decision_point,
        evaluate_orchestration_parallel_readiness,
        evaluate_wave3_catalog_readiness,
        evaluate_wave4_workflows_readiness,
        evaluate_wave5_production_path_readiness,
        evaluate_wave6_dynamic_readiness,
        evaluate_wave7_live_execution_readiness,
        run_orchestration_wave7_live_probe,
        set_isolated_parallel_write_production_path,
        set_orchestration_dynamic_workflows_gray,
        set_orchestration_workflows_gray,
        set_spawn_parallel_workers_catalog_gray,
    )
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True, exist_ok=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    verification = tmp_path / ".asteria" / "verification"
    verification.mkdir(parents=True)
    spawn = verification / "orchestration_spawn_real_20260607.json"
    route = verification / "orchestration_route_real_20260607.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)
    _write_wave2_evidence(verification / "orchestration_wave2_probe.json")

    validator = SchemaValidator(Path.cwd() / "schemas")
    readiness_w2 = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    decisions_dir = tmp_path / ".asteria" / "decisions"
    decisions_dir.mkdir(parents=True)

    w2 = build_orchestration_parallel_decision_point(run_id="run-test", readiness=readiness_w2)
    w2["status"] = "resolved"
    w2["selected_option_id"] = "wave2_maintainer_probe"
    w2["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0001.json").write_text(
        json.dumps(w2), encoding="utf-8"
    )

    w3_readiness = evaluate_wave3_catalog_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
    )
    w3 = build_wave3_catalog_decision_point(run_id="run-test", readiness=w3_readiness)
    w3["status"] = "resolved"
    w3["selected_option_id"] = "wave3_catalog_gray"
    w3["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0002.json").write_text(
        json.dumps(w3), encoding="utf-8"
    )
    (verification / "orchestration_wave3_catalog_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_spawn_parallel_workers_catalog_gray(
        agent_dir=tmp_path / ".asteria", validator=validator, enabled=True
    )

    policy = load_policy_config(tmp_path / ".asteria", validator)
    w4_readiness = evaluate_wave4_workflows_readiness(
        root=tmp_path,
        policy=policy,
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
    )
    w4 = build_wave4_workflows_decision_point(run_id="run-test", readiness=w4_readiness)
    w4["status"] = "resolved"
    w4["selected_option_id"] = "wave4_workflows_gray"
    w4["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0003.json").write_text(
        json.dumps(w4), encoding="utf-8"
    )
    (verification / "orchestration_wave4_workflows_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_orchestration_workflows_gray(agent_dir=tmp_path / ".asteria", validator=validator, enabled=True)

    w5_readiness = evaluate_wave5_production_path_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
        wave4_evidence_path=verification / "orchestration_wave4_workflows_probe.json",
    )
    w5 = build_wave5_production_path_decision_point(run_id="run-test", readiness=w5_readiness)
    w5["status"] = "resolved"
    w5["selected_option_id"] = "wave5_isolated_production_path"
    w5["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0004.json").write_text(
        json.dumps(w5), encoding="utf-8"
    )
    (verification / "orchestration_wave5_production_path.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_isolated_parallel_write_production_path(
        agent_dir=tmp_path / ".asteria", validator=validator, enabled=True
    )

    w6_readiness = evaluate_wave6_dynamic_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
        wave4_evidence_path=verification / "orchestration_wave4_workflows_probe.json",
        wave5_evidence_path=verification / "orchestration_wave5_production_path.json",
    )
    w6 = build_wave6_dynamic_decision_point(run_id="run-test", readiness=w6_readiness)
    w6["status"] = "resolved"
    w6["selected_option_id"] = "wave6_dynamic_workflows_gray"
    w6["resolved_at"] = "2026-06-07T00:00:00+08:00"
    (decisions_dir / "decision-orchestration-parallel-0005.json").write_text(
        json.dumps(w6), encoding="utf-8"
    )
    (verification / "orchestration_wave6_dynamic_probe.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    set_orchestration_dynamic_workflows_gray(
        agent_dir=tmp_path / ".asteria", validator=validator, enabled=True
    )

    bench = tmp_path / "benchmarks"
    bench.mkdir(parents=True)
    for name in (
        "orchestration_wave7_live_gate.json",
        "orchestration_wave7_live_manifest.json",
    ):
        src = Path.cwd() / "benchmarks" / name
        bench.joinpath(name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    w7_readiness = evaluate_wave7_live_execution_readiness(
        root=tmp_path,
        policy=load_policy_config(tmp_path / ".asteria", validator),
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        wave2_evidence_path=verification / "orchestration_wave2_probe.json",
        wave3_evidence_path=verification / "orchestration_wave3_catalog_probe.json",
        wave4_evidence_path=verification / "orchestration_wave4_workflows_probe.json",
        wave5_evidence_path=verification / "orchestration_wave5_production_path.json",
        wave6_evidence_path=verification / "orchestration_wave6_dynamic_probe.json",
    )
    assert w7_readiness.ready_for_live_probe is True

    result = run_orchestration_wave7_live_probe(repo_root=tmp_path, validator=validator)
    assert result.ok is True
    policy = load_policy_config(tmp_path / ".asteria", validator)
    agent_loop = policy.get("agent_loop") or {}
    assert agent_loop.get(LIVE_EXECUTION_GRAY_POLICY_KEY) is True
    assert agent_loop.get(DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY) is True
    assert agent_loop.get(PRODUCTION_PATH_POLICY_KEY) is True
    assert agent_loop.get("parallel_writes") is not True
    assert result.validation_run_path is not None
    assert result.validation_run_path.exists()


def test_wave8_beta_opt_in_enables_parallel_writes(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.orchestration_parallel_gray import (
        LIVE_EXECUTION_GRAY_POLICY_KEY,
        PARALLEL_WRITES_BETA_OPT_IN_KEY,
        PRODUCTION_PATH_POLICY_KEY,
        dynamic_ingress_eval_passed,
        evaluate_wave8_parallel_writes_beta_readiness,
        run_wave8_beta_opt_in_band,
        set_isolated_parallel_write_production_path,
        set_orchestration_dynamic_live_execution_gray,
        set_orchestration_dynamic_workflows_gray,
        set_parallel_writes_beta_opt_in,
    )
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    verification = agent_dir / "verification"
    verification.mkdir(parents=True)
    (verification / "orchestration_dynamic_ingress_real_20260607.json").write_text(
        json.dumps({"ok": True, "summary": {"hit_rate": 1.0}}),
        encoding="utf-8",
    )
    (verification / "orchestration_wave7_live_probe.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    decisions_dir = agent_dir / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "decision-orchestration-parallel-0006.json").write_text(
        json.dumps(
            {
                "decision_id": "decision-orchestration-parallel-0006",
                "status": "resolved",
                "selected_option_id": "wave7_live_execution_gray",
            }
        ),
        encoding="utf-8",
    )

    set_isolated_parallel_write_production_path(agent_dir=agent_dir, validator=validator, enabled=True)
    set_orchestration_dynamic_workflows_gray(agent_dir=agent_dir, validator=validator, enabled=True)
    set_orchestration_dynamic_live_execution_gray(agent_dir=agent_dir, validator=validator, enabled=True)

    ingress_ok, _ = dynamic_ingress_eval_passed(tmp_path)
    assert ingress_ok is True

    readiness = evaluate_wave8_parallel_writes_beta_readiness(
        root=tmp_path,
        policy=load_policy_config(agent_dir, validator),
    )
    assert readiness.wave7_probe_ok is True
    assert readiness.ingress_eval_ok is True

    set_parallel_writes_beta_opt_in(agent_dir=agent_dir, validator=validator, enabled=True)
    band = run_wave8_beta_opt_in_band(repo_root=tmp_path, validator=validator)
    assert band["ok"] is True

    policy = load_policy_config(agent_dir, validator)
    agent_loop = policy.get("agent_loop") or {}
    assert agent_loop.get("parallel_writes") is True
    assert agent_loop.get(PARALLEL_WRITES_BETA_OPT_IN_KEY) is True
    assert agent_loop.get(LIVE_EXECUTION_GRAY_POLICY_KEY) is True
    assert agent_loop.get(PRODUCTION_PATH_POLICY_KEY) is True
