from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_path() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

_ensure_src_path()

from asteria_runtime.real_model_smoke import *  # noqa: E402,F403
from asteria_runtime.real_model_smoke import (  # noqa: E402
    _accept_budget_paused_success,  # noqa: F401
    main,
)


if __name__ == "__main__":
    main()
