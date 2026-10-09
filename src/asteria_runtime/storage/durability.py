from __future__ import annotations

import os
from pathlib import Path


def fsync_existing_file(path: Path) -> None:
    """Flush a file already on disk to durable storage (audit debt #5②).

    Per-write close() only guarantees the bytes reached the OS page cache — a process
    kill survives that, but an OS crash / power loss loses the tail. This reopens the
    file with write access (required for FlushFileBuffers on Windows) and fsyncs it.
    Letting fsync errors propagate is deliberate: a silent durability lie is worse than
    a loud failure on an exotic filesystem."""
    with open(path, "r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())
