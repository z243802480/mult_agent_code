from pathlib import Path

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.tools.patch_tools import ApplyPatchTool, DiffWorkspaceTool


def context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id=None,
        policy={
            "protected_paths": [".env", "secrets/", ".git/"],
            "permissions": {},
        },
        validator=SchemaValidator(Path("schemas")),
    )


def test_apply_patch_changes_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    patch = """--- a/a.txt
+++ b/a.txt
@@
 hello
-world
+agent
"""

    result = ApplyPatchTool().run(context(tmp_path), patch)

    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello\nagent\n"


def test_apply_patch_accepts_legacy_diff_argument(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    diff = """--- a/a.txt
+++ b/a.txt
@@
 hello
-world
+agent
"""

    result = ApplyPatchTool().run(context(tmp_path), diff=diff)

    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello\nagent\n"


def test_apply_patch_changes_one_hunk_inside_larger_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    patch = """--- a/a.txt
+++ b/a.txt
@@
 two
-three
+agent
"""

    result = ApplyPatchTool().run(context(tmp_path), patch)

    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\ntwo\nagent\n"


def test_apply_patch_rejects_context_mismatch(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("different\n", encoding="utf-8")
    patch = """--- a/a.txt
+++ b/a.txt
@@
-hello
+agent
"""

    result = ApplyPatchTool().run(context(tmp_path), patch)

    assert not result.ok
    assert result.error == "patch_context_mismatch"


def test_apply_patch_denies_protected_path(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    patch = """--- a/.env
+++ b/.env
@@
-SECRET=1
+SECRET=2
"""

    try:
        ApplyPatchTool().run(context(tmp_path), patch)
    except PermissionError as exc:
        assert "protected" in str(exc)
    else:
        raise AssertionError("Expected protected path denial")


def test_diff_workspace_generates_unified_diff(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("new\n", encoding="utf-8")

    result = DiffWorkspaceTool().run(context(tmp_path), path="a.txt", original="old\n")

    assert result.ok
    assert "-old" in result.data["diff"]
    assert "+new" in result.data["diff"]
