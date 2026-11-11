from pathlib import Path
import subprocess
import sys

import pytest

from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.core.workspace_writer_lock import WorkspaceBusyError
from tests.integration.test_cancel_command import _zombie_run


def test_resume_does_not_initialize_an_uninitialized_workspace(tmp_path):
    with pytest.raises(RuntimeError, match="not initialized"):
        ResumeCommand(tmp_path).run()
    assert not (tmp_path / ".asteria").exists()


def test_resume_refuses_before_mutating_tasks_while_another_writer_is_alive(tmp_path):
    run_id = _zombie_run(tmp_path)
    path = tmp_path / ".asteria/runs" / run_id / "task_plan.json"
    before = path.read_bytes()
    source = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys,time;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
        "from asteria_runtime.core.workspace_writer_lock import workspace_writer_lock;"
        "\nwith workspace_writer_lock(Path(sys.argv[2]),command='test'):\n"
        " print('READY',flush=True);time.sleep(30)"
    )
    process = subprocess.Popen([sys.executable, "-c", code, str(source), str(tmp_path)],
                               stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "READY"
        with pytest.raises(WorkspaceBusyError):
            ResumeCommand(tmp_path, run_id).run()
        assert path.read_bytes() == before
    finally:
        process.terminate()
        process.wait(timeout=10)
