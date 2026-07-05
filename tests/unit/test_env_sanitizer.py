"""Credential scrub for the model shell's child environment (defense-in-depth vs interpreter exfil)."""
import os

from asteria_runtime.security.env_sanitizer import is_secret_env_name, sanitize_subprocess_env


def test_is_secret_env_name_matches_credential_markers() -> None:
    for name in [
        "AGENT_MODEL_API_KEY",
        "AGENT_MODEL_STRONG_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "DB_PASSWORD",
        "SOME_CREDENTIAL",
        "ANTHROPIC_BASE_URL",  # harness provider config family (prefix), stripped too
    ]:
        assert is_secret_env_name(name), name


def test_is_secret_env_name_keeps_ordinary_vars() -> None:
    for name in ["PATH", "HOME", "SYSTEMROOT", "TEMP", "LANG", "PWD", "MY_APP_CONFIG", "PYTHONPATH"]:
        assert not is_secret_env_name(name), name


def test_sanitize_removes_secrets_keeps_rest() -> None:
    env = {
        "PATH": "/usr/bin",
        "AGENT_MODEL_API_KEY": "sk-secret",
        "AGENT_MODEL_STRONG_API_KEY": "sk-secret-2",
        "ANTHROPIC_BASE_URL": "https://internal.gateway",
        "GITHUB_TOKEN": "ghp_x",
        "MY_APP_CONFIG": "keepme",
    }
    scrubbed, removed = sanitize_subprocess_env(env)
    assert scrubbed == {"PATH": "/usr/bin", "MY_APP_CONFIG": "keepme"}
    assert removed == sorted(
        ["AGENT_MODEL_API_KEY", "AGENT_MODEL_STRONG_API_KEY", "ANTHROPIC_BASE_URL", "GITHUB_TOKEN"]
    )


def test_sanitize_defaults_to_process_environ(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "sk-live")
    monkeypatch.setenv("PLAIN_VISIBLE_VAR", "ok")
    scrubbed, removed = sanitize_subprocess_env()
    assert "AGENT_MODEL_API_KEY" not in scrubbed
    assert scrubbed.get("PLAIN_VISIBLE_VAR") == "ok"
    assert "AGENT_MODEL_API_KEY" in removed


def test_sanitize_does_not_mutate_source() -> None:
    env = {"AGENT_MODEL_API_KEY": "sk", "PATH": "/bin"}
    sanitize_subprocess_env(env)
    assert env == {"AGENT_MODEL_API_KEY": "sk", "PATH": "/bin"}
    assert "AGENT_MODEL_API_KEY" not in os.environ or True  # sanity: no accidental global mutation
