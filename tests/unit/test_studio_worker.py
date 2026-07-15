"""Warm worker (ADR-0029 ②) — protocol, per-request env routing, and loop resilience.

The worker reuses the same ``RunCommand`` the CLI does, which is covered by the run integration
tests. Here we monkeypatch ``RunCommand`` so these stay hermetic and fast: we are testing the
*worker's* contract (control protocol, event-sink env override, kwargs it passes, and that one bad
run does not kill the serve loop) — not the run itself.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import asteria_runtime.commands.run_command as run_command_module
from asteria_runtime import studio_worker
from asteria_runtime.models.studio_event_sink import StudioModelEventSink

PREFIX = studio_worker.CONTROL_PREFIX


def _control_messages(captured: str) -> list[dict]:
    out = []
    for line in captured.splitlines():
        if line.startswith(PREFIX):
            out.append(json.loads(line[len(PREFIX) :]))
    return out


def test_ready_then_malformed_and_unknown_mode(capsys):
    stream = io.StringIO('not json\n{"id":"r1","mode":"review"}\n')
    studio_worker.serve(stream)
    msgs = _control_messages(capsys.readouterr().out)
    assert msgs[0] == {"event": "ready"}
    assert msgs[1]["event"] == "error" and "malformed" in msgs[1]["error"]
    assert msgs[2]["id"] == "r1" and "not served" in msgs[2]["error"]


def test_apply_studio_env_routes_the_event_sink(tmp_path, monkeypatch):
    monkeypatch.delenv("ASTERIA_STUDIO_EVENT_SINK", raising=False)
    monkeypatch.delenv("ASTERIA_STUDIO_SESSION_ID", raising=False)
    monkeypatch.delenv("ASTERIA_STUDIO_PHASE", raising=False)
    sink_path = tmp_path / "events.jsonl"
    studio_worker._apply_studio_env(
        {"event_sink": str(sink_path), "session_id": "sess-42", "phase": "execute"}
    )
    # The sink reads these env vars fresh on construction — this is the seam the worker relies on to
    # route each run's events to the right session while sharing one process.
    sink = StudioModelEventSink()
    assert sink.path == sink_path
    assert sink.session_id == "sess-42"
    assert sink.phase == "execute"
    assert sink.enabled is True
    # A request without a sink clears it, so a later run cannot leak into a previous session's file.
    studio_worker._apply_studio_env({"session_id": None})
    assert StudioModelEventSink().enabled is False


def test_run_request_passes_faithful_kwargs_and_returns_run_id(capsys, tmp_path, monkeypatch):
    seen = {}

    class FakeRunCommand:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def run(self):
            return SimpleNamespace(run_id="run-20260715-0007", status="completed")

    monkeypatch.setattr(run_command_module, "RunCommand", FakeRunCommand)

    request = {
        "id": "job-1",
        "mode": "run",
        "root": str(tmp_path),
        "goal": "build a thing",
        "max_iterations": 8,
        "max_tasks_per_iteration": 1,
        "no_research": True,
        "event_sink": str(tmp_path / "events.jsonl"),
        "session_id": "sess-1",
        "phase": "execute",
    }
    studio_worker.serve(io.StringIO(json.dumps(request) + "\n"))
    msgs = _control_messages(capsys.readouterr().out)
    done = [m for m in msgs if m.get("event") == "done"][0]
    assert done["id"] == "job-1"
    assert done["run_id"] == "run-20260715-0007"
    assert done["status"] == "completed"
    assert done["exit_code"] == 0

    # Kwargs must mirror the cold CLI path: --no-research → enable_research False, and the Studio
    # session_id must NOT be smuggled in as the run_id (that would be an invalid run id).
    assert str(seen["root"]) == str(tmp_path)
    assert seen["goal"] == "build a thing"
    assert seen["max_iterations"] == 8
    assert seen["enable_research"] is False
    assert seen["run_id"] is None
    assert seen["mode"] == "goal"


def test_one_failing_run_does_not_kill_the_loop(capsys, tmp_path, monkeypatch):
    calls = {"n": 0}

    class FlakyRunCommand:
        def __init__(self, **kwargs):
            calls["n"] += 1

        def run(self):
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return SimpleNamespace(run_id="run-20260715-0008", status="completed")

    monkeypatch.setattr(run_command_module, "RunCommand", FlakyRunCommand)

    req = lambda i: json.dumps(  # noqa: E731 — terse test helper
        {"id": f"job-{i}", "mode": "run", "root": str(tmp_path), "goal": "g"}
    )
    studio_worker.serve(io.StringIO(req(1) + "\n" + req(2) + "\n"))
    msgs = _control_messages(capsys.readouterr().out)
    first = [m for m in msgs if m.get("id") == "job-1"][0]
    second = [m for m in msgs if m.get("id") == "job-2"][0]
    assert first["event"] == "error" and "boom" in first["error"]
    assert second["event"] == "done"  # the loop survived and served the next request
