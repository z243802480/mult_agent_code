"""专家注册表(MoE 骨架)单测。"""

from __future__ import annotations

from asteria_runtime.core.expert_registry import (
    DEFAULT_EXPERTS,
    expert_roles,
    resolve_expert,
)


def test_resolve_known_roles() -> None:
    assert resolve_expert("coder").role == "coder"
    assert resolve_expert("diagnostic").role == "diagnostic"
    assert resolve_expert("reviewer").role == "reviewer"
    assert resolve_expert("researcher").role == "researcher"


def test_resolve_is_case_insensitive_and_trims() -> None:
    assert resolve_expert("  Coder ").role == "coder"


def test_unknown_role_falls_back_to_coder() -> None:
    assert resolve_expert("wizard").role == "coder"
    assert resolve_expert("").role == "coder"
    assert resolve_expert(None).role == "coder"


def test_readonly_experts_are_flagged() -> None:
    assert resolve_expert("reviewer").read_only is True
    assert resolve_expert("researcher").read_only is True
    assert resolve_expert("coder").read_only is False
    assert resolve_expert("diagnostic").read_only is False


def test_experts_bundle_methodology_skills() -> None:
    # Each expert foregrounds the methodology procedures that fit its job.
    assert "skill__debug" in resolve_expert("diagnostic").methodology_skills
    assert "skill__verify" in resolve_expert("coder").methodology_skills


def test_expert_roles_lists_all() -> None:
    assert set(expert_roles()) == set(DEFAULT_EXPERTS)
    assert "coder" in expert_roles()
