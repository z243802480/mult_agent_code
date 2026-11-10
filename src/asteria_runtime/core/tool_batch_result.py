"""Carry completed results across a batch-aborting exception without replaying calls."""

from typing import Any


class ToolBatchError(RuntimeError):
    def __init__(self, results: list[Any], failed_call: dict, cause: Exception,
                 skipped_calls: list[dict]) -> None:
        super().__init__(str(cause))
        self.results = list(results)
        self.failed_call = failed_call
        self.cause = cause
        self.skipped_calls = list(skipped_calls)
