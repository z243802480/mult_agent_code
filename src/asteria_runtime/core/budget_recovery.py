"""Recover budget high-water marks from durable evidence without rewriting its history."""

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from asteria_runtime.core.budget import classify_tool_budget_class
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator

if TYPE_CHECKING:
    from asteria_runtime.core.budget import BudgetController


def recover_budget(budget: "BudgetController", run_dir: Path, validator: SchemaValidator) -> None:
    store = JsonlStore(validator)
    models = store.read_all(run_dir / "model_calls.jsonl", "model_call")
    tools = store.read_all(run_dir / "tool_calls.jsonl", "tool_call")
    skills = store.read_all(run_dir / "skill_invocations.jsonl", "skill_invocation")
    mcp = store.read_all(run_dir / "mcp_invocations.jsonl", "mcp_invocation")
    before = budget.cost_report()
    usage = budget.usage
    usage.model_calls = max(usage.model_calls, len(models))
    for tier in ("strong", "cheap"):
        name = tier + "_model_calls"
        setattr(usage, name, max(getattr(usage, name), sum(r.get("model_tier") == tier for r in models)))
    unknown_usage = sum(r.get("input_tokens") is None or r.get("output_tokens") is None for r in models)
    for key in ("input_tokens", "output_tokens"):
        field = "estimated_" + key
        current = getattr(usage, field)
        if any(r.get(key) is None for r in models):
            setattr(usage, field, None)
        elif current is not None:
            setattr(usage, field, max(current, sum(r.get(key, 0) for r in models)))

    charged_names = []
    ambiguous = 0
    for rows, name in ((tools, "local"), (skills, "skill"), (mcp, "mcp")):
        for row in rows:
            charged = row.get("budget_charged")
            if charged is False:
                continue
            if charged is None:
                ambiguous += 1
                if name != "local" and (row.get("capability_decision") or {}).get("decision") == "deny":
                    ambiguous -= 1
                    continue
            if name == "local":
                charged_names.append(row["tool_name"])
            elif name == "skill":
                charged_names.append("skill." + row["skill_name"])
            else:
                charged_names.append("mcp." + row["server_name"] + "/" + row["tool_name"])
    breakdown = Counter(classify_tool_budget_class(name) for name in charged_names)
    usage.tool_calls = max(usage.tool_calls, len(charged_names))
    for name, count in breakdown.items():
        usage.tool_call_breakdown[name] = max(usage.tool_call_breakdown.get(name, 0), count)
    usage.tool_budget_units = max(usage.tool_budget_units, sum(
        count * budget._tool_budget_weight(name) for name, count in breakdown.items()
    ))
    reserved = max(0, usage.model_calls - len(models))
    reserved_tools = max(0, usage.tool_calls - len(charged_names))
    if budget.cost_report() != before or ambiguous or unknown_usage or reserved or reserved_tools:
        budget.accounting_recovery = {
            "source": "durable_ledgers", "precision": "conservative" if ambiguous or unknown_usage or reserved or reserved_tools else "record_floor",
            "observed_model_records": len(models), "unrecorded_model_attempts": reserved,
            "unrecorded_tool_attempts": reserved_tools,
            "ambiguous_tool_attempts": ambiguous, "unknown_usage_records": unknown_usage,
        }
