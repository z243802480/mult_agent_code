from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.models.base import ModelClient
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass
class CoderAgent:
    """Run-scoped carrier of the coding model client (ADR-0016).

    RA7b deleted the FSM round loop; the model-driven spine (``core.model_driven_turn``) is the sole
    execution path and drives the model itself. ``CoderAgent`` no longer proposes ``ExecutionAction``
    objects — its former ``propose_action`` machinery went with the FSM. It survives only as the
    holder of the run-scoped ``model_client`` / ``validator`` the spine reads
    (``execute_command._run_model_driven_task`` passes ``coder.model_client`` into the turn loop).
    """

    model_client: ModelClient
    validator: SchemaValidator
