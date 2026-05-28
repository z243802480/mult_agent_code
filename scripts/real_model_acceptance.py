from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_path() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_src_path()

from asteria_runtime.real_model_acceptance import (  # noqa: E402,F401
    SCENARIOS,
    SUITES,
    TimeoutBudget,
    aggregate_results,
    apply_timeout_budget_env,
    classify_acceptance_subprocess_failure,
    readiness_ready,
    main,
)


if __name__ == "__main__":
    main()
