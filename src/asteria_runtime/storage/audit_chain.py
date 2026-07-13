"""Append-only tamper-evidence for the `.asteria` audit JSONL logs (S77 P1 · hash chain).

Closes the audit-integrity gap: the runtime's JSONL evidence was pure append with no integrity
protection, so any process could rewrite it after the fact and no one could tell (S77 moat hole).

**What this does (honest scope)**: maintains a per-file hash chain in a co-located `<file>.chain`
sidecar. Each chain entry binds one JSONL record to the previous one
(``chain_i = sha256(chain_{i-1} + "\\n" + sha256(record_i))``), so any later **edit / deletion /
insertion / reordering** of a record makes the recomputed chain diverge and the ``verify`` walk
flags exactly where. This makes the audit log **tamper-evident**.

**What this does NOT do (honest limitation)**: it is not tamper-*proof*. The chain sidecar sits
next to the log, so an attacker with write access who edits a record AND re-runs the chain defeats
detection. Full non-repudiation needs the chain head anchored somewhere the attacker cannot reach
(external notarization / signing) — deferred. The head hash produced here is exactly the value a
later cut would anchor.

Gated off by default (``configure_audit_chain(True)`` from policy ``audit.tamper_evident``): when
off there is zero cost and zero behavior change. When on, ``JsonlStore.append`` / ``rewrite_all``
maintain the chain at the single append chokepoint (covers every audit JSONL — events,
user_progress, decisions, capability_decisions, tool_calls, task_execution_evidence, …).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Module-level toggle: audit integrity is a cross-cutting policy, set once at runtime bootstrap from
# ``policy["audit"]["tamper_evident"]``. Off by default → JsonlStore behaves byte-identically.
_ENABLED = False

_GENESIS = "GENESIS"


def configure_audit_chain(enabled: bool) -> None:
    """Enable/disable audit-chain maintenance process-wide (called from policy at run/execute start)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def audit_chain_enabled() -> bool:
    return _ENABLED


def configure_from_policy(policy: dict[str, Any] | None) -> None:
    """Set the process-wide toggle from ``policy["audit"]["tamper_evident"]`` (default off)."""
    audit = (policy or {}).get("audit")
    audit = audit if isinstance(audit, dict) else {}
    configure_audit_chain(bool(audit.get("tamper_evident", False)))


def is_audit_file(path: Path) -> bool:
    """Every `.jsonl` under the run dir is an audit log; the `.jsonl.chain` sidecars end in `.chain`
    (not `.jsonl`) so they are naturally excluded."""
    return path.name.endswith(".jsonl")


def chain_path(path: Path) -> Path:
    return path.with_name(path.name + ".chain")


def _record_hash(record_line: str) -> str:
    return hashlib.sha256(record_line.encode("utf-8")).hexdigest()


def _chain_step(prev_chain: str, record_hash: str) -> str:
    return hashlib.sha256(f"{prev_chain}\n{record_hash}".encode("utf-8")).hexdigest()


def _last_chain_hash(cpath: Path) -> str:
    """Head of the chain (O(1) bounded tail read — chain entries are tiny)."""
    if not cpath.exists():
        return _GENESIS
    size = cpath.stat().st_size
    if size == 0:
        return _GENESIS
    with cpath.open("rb") as handle:
        handle.seek(max(0, size - 2048))
        tail = handle.read().decode("utf-8", errors="replace")
    lines = [line for line in tail.splitlines() if line.strip()]
    if not lines:
        return _GENESIS
    try:
        return str(json.loads(lines[-1])["chain_sha256"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return _GENESIS


def append_chain_entry(path: Path, record_line: str) -> None:
    """Append one chain entry binding ``record_line`` (the exact JSONL text, no newline) to the head."""
    cpath = chain_path(path)
    prev = _last_chain_hash(cpath)
    rhash = _record_hash(record_line)
    entry = {
        "seq": _chain_len(cpath) + 1,
        "record_sha256": rhash,
        "chain_sha256": _chain_step(prev, rhash),
    }
    with cpath.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def rechain_file(path: Path, record_lines: list[str]) -> None:
    """Rebuild the whole chain over ``record_lines`` (for an atomic ``rewrite_all`` — a legitimate
    mutation like a decision status transition re-seals; a raw edit that skips this is detected)."""
    cpath = chain_path(path)
    prev = _GENESIS
    out: list[str] = []
    for index, line in enumerate(record_lines, start=1):
        rhash = _record_hash(line)
        prev = _chain_step(prev, rhash)
        out.append(json.dumps({"seq": index, "record_sha256": rhash, "chain_sha256": prev}, ensure_ascii=False))
    tmp = cpath.with_name(cpath.name + ".tmp")
    tmp.write_text("".join(line + "\n" for line in out), encoding="utf-8")
    tmp.replace(cpath)


def _chain_len(cpath: Path) -> int:
    if not cpath.exists():
        return 0
    return sum(1 for line in cpath.read_text(encoding="utf-8").splitlines() if line.strip())


def verify_file(path: Path) -> dict[str, Any]:
    """Recompute the chain from ``path`` and compare it to the ``<path>.chain`` sidecar.

    Returns ``{file, ok, records, reason?, break_seq?}``. ``ok`` is False when a record was edited,
    deleted, inserted, or reordered (recomputed chain diverges), when the sidecar is missing while
    the log has records, or when the two lengths disagree (append-after-tamper / truncation).
    """
    cpath = chain_path(path)
    record_lines = _nonempty_lines(path)
    chain_entries = _read_chain(cpath)
    result: dict[str, Any] = {"file": path.name, "records": len(record_lines)}
    if not chain_entries:
        if record_lines:
            return {**result, "ok": False, "reason": "chain sidecar missing while log has records"}
        return {**result, "ok": True}
    if len(record_lines) != len(chain_entries):
        return {
            **result,
            "ok": False,
            "reason": f"length mismatch: {len(record_lines)} records vs {len(chain_entries)} chain entries",
        }
    prev = _GENESIS
    for index, (line, entry) in enumerate(zip(record_lines, chain_entries), start=1):
        rhash = _record_hash(line)
        prev = _chain_step(prev, rhash)
        if entry.get("record_sha256") != rhash or entry.get("chain_sha256") != prev:
            return {**result, "ok": False, "reason": "record hash / chain diverged", "break_seq": index}
    return {**result, "ok": True}


def verify_run(run_dir: Path) -> dict[str, Any]:
    """Verify every chained audit file under ``run_dir``. ``ok`` is True only if all pass."""
    files = sorted(p for p in run_dir.glob("*.jsonl") if chain_path(p).exists())
    checks = [verify_file(path) for path in files]
    return {
        "run_dir": str(run_dir),
        "ok": all(check["ok"] for check in checks),
        "chained_files": len(checks),
        "checks": checks,
    }


def _nonempty_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_chain(cpath: Path) -> list[dict[str, Any]]:
    if not cpath.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in cpath.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({})  # a corrupt chain line is itself a tamper signal → length/hash fails
    return entries
