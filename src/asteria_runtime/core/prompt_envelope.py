from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_harness import AgentHarness, PromptEnvelope
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


@dataclass(frozen=True)
class PromptEnvelopeRecord:
    envelope: PromptEnvelope
    path: Path
    data: dict[str, Any]

    def context_ref(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "section_order": self.data["section_order"],
            "content_hash": self.data["content_hash"],
            "sections": [
                {
                    "name": section["name"],
                    "summary": section["summary"],
                    "evidence_refs": section.get("evidence_refs", []),
                }
                for section in self.data["sections"]
            ],
            "capability_manifest": self.data["capability_manifest"],
        }


def persist_prompt_envelope(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    mode: str,
    policy: dict[str, Any],
    validator: SchemaValidator,
    tool_names: list[str] | None = None,
    event_logger: EventLogger | None = None,
    progress_logger: UserProgressLogger | None = None,
    phase: str | None = None,
    actor: str = "AgentHarness",
) -> PromptEnvelopeRecord:
    project_guidance_path = root / "AGENTS.md"
    project_guidance = (
        project_guidance_path.read_text(encoding="utf-8")
        if project_guidance_path.exists()
        else ""
    )
    envelope = AgentHarness(policy, tool_names=tool_names).prompt_envelope(
        run_id=run_id,
        mode=mode,
        project_guidance=project_guidance,
        project_guidance_refs=["AGENTS.md"] if project_guidance else [],
    )
    data = envelope.to_dict()
    path = _prompt_envelope_path(run_dir, mode)
    JsonStore(validator).write(path, data, "prompt_envelope")
    context_ref = {
        "path": str(path),
        "sections": data["section_order"],
        "content_hash": data["content_hash"],
    }
    if event_logger is not None:
        event_logger.record(
            run_id,
            "prompt_envelope_created",
            actor,
            f"Prompt envelope for {mode} mode was persisted.",
            {"artifact": str(path), **context_ref},
        )
    if progress_logger is not None:
        progress_logger.record(
            run_id=run_id,
            channel="progress",
            event_type="message",
            phase=phase or mode,
            status="running",
            title="能力环境已装载",
            summary=(
                "Runtime persisted the prompt envelope and exposed available modes, "
                "tools, permissions, and safety boundaries to the model."
            ),
            data={
                "capability_manifest": envelope.capability_manifest.to_dict(),
                "prompt_envelope": context_ref,
            },
            artifact_refs=[str(path)],
            evidence_refs=[str(path)],
            call_chain=[actor, "AgentHarness"] if actor != "AgentHarness" else ["AgentHarness"],
            execution_chain=[mode, "capability_manifest"],
        )
    return PromptEnvelopeRecord(envelope=envelope, path=path, data=data)


def _prompt_envelope_path(run_dir: Path, mode: str) -> Path:
    if mode == "plan":
        return run_dir / "prompt_envelope.json"
    return run_dir / f"prompt_envelope_{mode}.json"
