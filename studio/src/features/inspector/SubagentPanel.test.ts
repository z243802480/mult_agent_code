import { describe, expect, it } from "vitest";
import { buildExpertRows, buildReconciliation } from "./SubagentPanel";
import type { StudioEvent } from "../../types";

// Cards shaped exactly as the runtime writes them (execute_command `_run_child` / merge-gate card).
// B4 added batch identity + what-the-expert-did; before that the panel could only show role/status,
// and PARALLELISM was not in the evidence at all (the smoke had to guess it from card ordering).
function card(data: Record<string, unknown>, summary = ""): StudioEvent {
  return {
    event_id: `e-${Math.random()}`,
    transcript_kind: "subagent_summary",
    display_level: "main",
    status: "completed",
    summary,
    data,
  } as unknown as StudioEvent;
}

const BATCH = {
  batch_id: "t1-batch-01",
  batch_size: 2,
  batch_mode: "isolated_writes",
  concurrent: true,
};

describe("buildExpertRows", () => {
  it("reads parallelism, changed files and tier off a concurrent write batch", () => {
    const rows = buildExpertRows([
      card({
        ...BATCH,
        batch_index: 0,
        subagent_role: "coder",
        child_task_id: "t1-sub-01",
        subagent_phase: "dispatch",
      }),
      card({
        ...BATCH,
        batch_index: 1,
        subagent_role: "coder",
        child_task_id: "t1-sub-02",
        subagent_phase: "dispatch",
      }),
      card({
        ...BATCH,
        batch_index: 0,
        subagent_role: "coder",
        child_task_id: "t1-sub-01",
        subagent_phase: "result",
        ok: true,
        iterations: 2,
        model_tier: "strong",
        changed_files: ["src/alpha.py"],
      }),
      card({
        ...BATCH,
        batch_index: 1,
        subagent_role: "coder",
        child_task_id: "t1-sub-02",
        subagent_phase: "result",
        ok: true,
        iterations: 3,
        model_tier: "strong",
        changed_files: ["src/beta.py"],
      }),
    ]);

    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.childTaskId)).toEqual(["t1-sub-01", "t1-sub-02"]);
    expect(rows.every((r) => r.concurrent)).toBe(true);
    expect(rows.every((r) => r.status === "done")).toBe(true);
    expect(rows.map((r) => r.changedFiles)).toEqual([["src/alpha.py"], ["src/beta.py"]]);
    expect(rows.map((r) => r.modelTier)).toEqual(["strong", "strong"]);
  });

  it("never claims parallelism for a serial delegation", () => {
    // A serial spawn carries NO batch — the runtime does not stamp `concurrent`, so the UI must not
    // invent it. (Regression guard: the old smoke inferred concurrency from card order and would.)
    const rows = buildExpertRows([
      card({ subagent_role: "coder", child_task_id: "t1-sub-01", subagent_phase: "dispatch" }),
      card({
        subagent_role: "coder",
        child_task_id: "t1-sub-01",
        subagent_phase: "result",
        ok: true,
        changed_files: ["src/alpha.py"],
      }),
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0].concurrent).toBe(false);
  });

  it("marks a failed expert as failed", () => {
    const rows = buildExpertRows([
      card({ subagent_role: "reviewer", child_task_id: "t1-sub-01", subagent_phase: "dispatch" }),
      card({
        subagent_role: "reviewer",
        child_task_id: "t1-sub-01",
        subagent_phase: "result",
        ok: false,
      }),
    ]);
    expect(rows[0].status).toBe("failed");
  });
});

describe("buildReconciliation", () => {
  it("surfaces the merge gate verdict verbatim (the card already names the conflicting file)", () => {
    const blocked = buildReconciliation([
      card(
        { subagent_phase: "merge_gate", ok: false, batch_id: "t1-batch-01" },
        "并发隔离写被合并门阻止：src/shared.py: claimed by multiple tasks",
      ),
    ]);
    expect(blocked?.ok).toBe(false);
    expect(blocked?.summary).toContain("src/shared.py");
  });

  it("is null when no write batch was reconciled (readonly fan-out)", () => {
    expect(
      buildReconciliation([
        card({ subagent_role: "reviewer", child_task_id: "t1-sub-01", subagent_phase: "result" }),
      ]),
    ).toBeNull();
  });
});
