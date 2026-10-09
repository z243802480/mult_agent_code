import json
from pathlib import Path

from asteria_runtime.storage import audit_chain
from asteria_runtime.storage.jsonl_store import JsonlStore


def _append(store: JsonlStore, path: Path, n: int) -> None:
    for index in range(1, n + 1):
        store.append(path, {"seq": index, "note": f"event-{index}"})


def test_chain_off_by_default_writes_no_sidecar(tmp_path: Path) -> None:
    audit_chain.configure_audit_chain(False)
    path = tmp_path / "decisions.jsonl"
    _append(JsonlStore(), path, 3)
    assert not audit_chain.chain_path(path).exists()  # zero cost / no behavior change when off


def test_chain_on_verifies_intact_append_only_log(tmp_path: Path) -> None:
    audit_chain.configure_audit_chain(True)
    path = tmp_path / "decisions.jsonl"
    _append(JsonlStore(), path, 5)
    assert audit_chain.chain_path(path).exists()
    result = audit_chain.verify_file(path)
    assert result["ok"] is True
    assert result["records"] == 5
    audit_chain.configure_audit_chain(False)


def test_chain_detects_edited_record(tmp_path: Path) -> None:
    audit_chain.configure_audit_chain(True)
    path = tmp_path / "user_progress.jsonl"
    _append(JsonlStore(), path, 4)
    audit_chain.configure_audit_chain(False)  # attacker edits offline, chain not updated
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = '{"seq": 3, "note": "TAMPERED"}'
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = audit_chain.verify_file(path)
    assert result["ok"] is False
    assert result["break_seq"] == 3


def test_chain_detects_deleted_record(tmp_path: Path) -> None:
    audit_chain.configure_audit_chain(True)
    path = tmp_path / "tool_calls.jsonl"
    _append(JsonlStore(), path, 4)
    audit_chain.configure_audit_chain(False)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # drop a record to hide it — chain length no longer matches
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = audit_chain.verify_file(path)
    assert result["ok"] is False
    assert "length mismatch" in result["reason"]


def test_rewrite_all_rechains_and_stays_valid(tmp_path: Path) -> None:
    # A legitimate atomic rewrite (e.g. a decision status transition) re-seals the chain.
    audit_chain.configure_audit_chain(True)
    path = tmp_path / "decisions.jsonl"
    _append(JsonlStore(), path, 3)
    JsonlStore().rewrite_all(
        path, [{"seq": 1, "status": "approved"}, {"seq": 2, "status": "pending"}]
    )
    result = audit_chain.verify_file(path)
    assert result["ok"] is True
    assert result["records"] == 2
    audit_chain.configure_audit_chain(False)


def test_configure_from_policy_reads_flag() -> None:
    audit_chain.configure_from_policy({"audit": {"tamper_evident": True}})
    assert audit_chain.audit_chain_enabled() is True
    audit_chain.configure_from_policy({"audit": {"tamper_evident": False}})
    assert audit_chain.audit_chain_enabled() is False
    audit_chain.configure_from_policy({})  # missing section → off
    assert audit_chain.audit_chain_enabled() is False


def test_verify_run_aggregates_all_chained_files(tmp_path: Path) -> None:
    audit_chain.configure_audit_chain(True)
    store = JsonlStore()
    _append(store, tmp_path / "decisions.jsonl", 2)
    _append(store, tmp_path / "tool_calls.jsonl", 3)
    audit_chain.configure_audit_chain(False)

    run_report = audit_chain.verify_run(tmp_path)
    assert run_report["ok"] is True
    assert run_report["chained_files"] == 2

    # Tamper one file → the aggregate run verdict flips to tampered.
    dpath = tmp_path / "decisions.jsonl"
    dpath.write_text('{"seq": 1, "note": "x"}\n{"seq": 2, "note": "HACKED"}\n', encoding="utf-8")
    tampered = audit_chain.verify_run(tmp_path)
    assert tampered["ok"] is False


def test_chain_append_reads_only_the_tail_not_the_whole_file(
    tmp_path: Path, monkeypatch
) -> None:
    # O(1) per append: the seq rides the tail entry, so maintaining a long chain must not
    # re-read the whole sidecar per record (the old _chain_len did — O(N²) per run).
    audit_chain.configure_audit_chain(True)
    path = tmp_path / "events.jsonl"
    _append(JsonlStore(), path, 30)
    read_text_calls = 0
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        nonlocal read_text_calls
        read_text_calls += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    _append(JsonlStore(), path, 1)
    assert read_text_calls == 0  # bounded tail read uses open("rb"), never read_text


def test_chain_sidecar_is_fsynced_like_the_log(tmp_path: Path, monkeypatch) -> None:
    import os

    audit_chain.configure_audit_chain(True)
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    path = tmp_path / "events.jsonl"
    _append(JsonlStore(), path, 3)
    assert len(calls) == 6  # 3 log appends + 3 sidecar appends, each fsynced


def test_rechain_fsyncs_and_stays_verifiable(tmp_path: Path, monkeypatch) -> None:
    import os

    audit_chain.configure_audit_chain(True)
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    path = tmp_path / "events.jsonl"
    _append(JsonlStore(), path, 3)
    calls.clear()

    JsonlStore().rewrite_all(path, [{"seq": 1, "note": "rewritten"}])

    assert calls, "re-sealed chain must be fsynced before its atomic rename"
    assert audit_chain.verify_file(path)["ok"] is True


def test_both_policy_templates_flip_tamper_evident_on_together() -> None:
    # 1.2.165: the default flips for NEW workspaces; the repo-root and packaged copies of
    # policies.default.json must never drift apart (schema-dir twin lesson).
    import json

    repo_root = Path(__file__).resolve().parents[2]
    for template in (
        repo_root / "templates" / "policies.default.json",
        repo_root / "src" / "asteria_runtime" / "templates" / "policies.default.json",
    ):
        policy = json.loads(template.read_text(encoding="utf-8"))
        assert policy["audit"]["tamper_evident"] is True, template


def test_missing_audit_key_falls_back_to_off() -> None:
    # The flip is a TEMPLATE default (new workspaces via init). A policy that predates the
    # audit block, or omits it by hand, stays conservatively off — existing workspaces are
    # preserved untouched by init, so their evidence chain state never changes silently.
    audit_chain.configure_from_policy({})
    assert audit_chain.audit_chain_enabled() is False
    audit_chain.configure_from_policy({"audit": {}})
    assert audit_chain.audit_chain_enabled() is False


def test_plan_run_in_tamper_evident_workspace_chains_its_evidence(tmp_path: Path) -> None:
    # End to end through the real user path: init (writes the flipped template policy) ->
    # plan run -> the run's events are hash-chained and verify comes back clean.
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.commands.plan_command import PlanCommand

    InitCommand(tmp_path).run()
    policy = json.loads((tmp_path / ".asteria" / "policies.json").read_text(encoding="utf-8"))
    assert policy["audit"]["tamper_evident"] is True

    result = PlanCommand(
        tmp_path, "做一个密码测试工具", model_client=FakePlanClientForAudit()
    ).run()
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    assert (run_dir / "events.jsonl.chain").exists()
    report = audit_chain.verify_run(run_dir)
    assert report["ok"] is True, report
    assert report["chained_files"] >= 2  # events.jsonl + user_progress.jsonl at least


class FakePlanClientForAudit:
    def chat(self, request):
        from asteria_runtime.models.base import ChatResponse, TokenUsage
        import json as _json

        return ChatResponse(
            content=_json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "做一个密码测试工具",
                    "normalized_goal": "构建本地优先密码测试工具",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": [],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "提供密码强度评分",
                            "source": "inferred",
                            "acceptance": ["输入密码后显示评分"],
                        }
                    ],
                    "target_outputs": [],
                    "definition_of_done": ["可以运行"],
                    "verification_strategy": ["unit_tests"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )
