from pathlib import Path

from asteria_runtime.commands.replan_command import ReplanCommand

_EVIDENCE = {"evidence_id": "task-execution-0001", "failure_type": None, "summary": "blocked"}
_SOURCE = {"task_id": "task-0009", "title": "在 taskman.py 中添加 export 子命令"}


def _replan(tmp_path: Path) -> ReplanCommand:
    return ReplanCommand(tmp_path, run_id="run-1")


def test_chained_repair_title_stays_single_wrapped(tmp_path: Path) -> None:
    # R2-8: chained replans fed each repair's wrapped title back in as the next label, growing
    # matryoshkas three shells deep on the real dogfood run. The title must keep naming the
    # original task no matter how long the repair chain is.
    cmd = _replan(tmp_path)
    matryoshka = "修改「修改「为「在 taskman.py 中添加 export 子命令」补充验证」的预期产物」的预期产物"
    assert cmd._root_repair_label(matryoshka) == "在 taskman.py 中添加 export 子命令"

    title = cmd._title({**_SOURCE, "title": matryoshka}, _EVIDENCE, ["verification did not pass"])
    assert title == "修复「在 taskman.py 中添加 export 子命令」"
    assert "「修改「" not in title and "「为「" not in title


def test_plain_titles_pass_through_unpeeled(tmp_path: Path) -> None:
    cmd = _replan(tmp_path)
    # A task genuinely TITLED with corner brackets must not be mangled: only peel exact shells
    # this module itself produces.
    assert cmd._root_repair_label("修复「X」的补充说明") == "修复「X」的补充说明"
    assert cmd._root_repair_label("「」") == "「」"  # empty inner label: too short to peel
    assert cmd._root_repair_label("在 taskman.py 中添加 export 子命令") == "在 taskman.py 中添加 export 子命令"


def test_each_template_peels_to_its_own_inner_label(tmp_path: Path) -> None:
    cmd = _replan(tmp_path)
    assert cmd._root_repair_label("为「在 taskman.py 中添加 export 子命令」补充验证") == "在 taskman.py 中添加 export 子命令"
    assert cmd._root_repair_label("修复「在 taskman.py 中添加 export 子命令」") == "在 taskman.py 中添加 export 子命令"
