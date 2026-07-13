from asteria_runtime.core.permission_policy import autonomy_rings_default_on


def test_reviewed_auto_and_auto_default_rings_on() -> None:
    # Set-and-forget: the two auto-develop tiers turn the autonomy rings on by default.
    assert autonomy_rings_default_on("reviewed_auto") is True
    assert autonomy_rings_default_on("auto") is True
    # Legacy aliases resolve the same.
    assert autonomy_rings_default_on("balanced") is True


def test_ask_everything_keeps_rings_off() -> None:
    # Explicit step-by-step supervision keeps the rings off.
    assert autonomy_rings_default_on("ask_everything") is False
    assert autonomy_rings_default_on("ask") is False


def test_missing_or_unknown_mode_defaults_on() -> None:
    # Absent/unknown mode → treat as the run default (reviewed_auto) → on. Never blocks on a typo.
    assert autonomy_rings_default_on(None) is True
    assert autonomy_rings_default_on("") is True
    assert autonomy_rings_default_on("nonsense") is True
