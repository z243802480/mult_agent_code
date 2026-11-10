"""Select recorded verification evidence consistently for review and correctness scoring."""

from collections.abc import Iterable, Set


def discarded_task_ids(tasks: Iterable[dict]) -> set[str]:
    """Only explicitly identified discarded tasks may be excluded from scoring."""
    return {
        str(task["task_id"])
        for task in tasks
        if task.get("status") == "discarded" and task.get("task_id")
    }


def final_round_verification(
    execution_evidence: Iterable[dict], *, discarded_ids: Set[str] = frozenset()
) -> list[dict] | None:
    """Return each retained task's final observations, including failures.

    None means no final verification lists were recorded (legacy format). An empty
    list is authoritative: a recorded empty round must not inherit historical passes.
    Unattributed rows cannot supersede each other, so retain each of them.
    """
    latest_by_task: dict[str, dict] = {}
    unattributed: list[dict] = []
    for row in execution_evidence:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            unattributed.append(row)
        elif task_id not in discarded_ids:
            latest_by_task[task_id] = row

    observations: list[dict] | None = None
    for row in [*latest_by_task.values(), *unattributed]:
        results = row.get("verification_results")
        if isinstance(results, list):
            if observations is None:
                observations = []
            observations.extend(item for item in results if isinstance(item, dict))
    return observations


def verification_item_kind(item: dict) -> str:
    """Distinguish executable checks from artifact readbacks without trusting payload shape."""
    data = item.get("data")
    if not isinstance(data, dict):
        data = {}
    if item.get("requested_command") or data.get("requested_command") or data.get("command"):
        return "command"
    if data.get("path"):
        return "readback"
    return "other"
