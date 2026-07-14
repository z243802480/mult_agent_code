"""Platform-correct Popen flags for spawning a killable process group.

Why a module-level constant instead of an inline ternary: mypy narrows `sys.platform` only in an
`if` STATEMENT, not inside a conditional expression. Written as
`subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0`, the Windows-only attribute
is still checked on Linux and reported as an error — which is exactly what the type ratchet caught.
"""

from __future__ import annotations

import subprocess
import sys


if sys.platform == "win32":
    # New process group so the whole subtree can be signalled/killed (taskkill /T).
    NEW_PROCESS_GROUP_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    # POSIX has no creationflags; the equivalent isolation comes from start_new_session=True.
    NEW_PROCESS_GROUP_FLAGS = 0
