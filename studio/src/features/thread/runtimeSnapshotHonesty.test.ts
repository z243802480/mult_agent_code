import { describe, expect, it } from "vitest";
import { runtimeSnapshotActionable, sessionWorkflowState } from "./RuntimeSnapshot";
import type { OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";

// Regression pins for the next-step bar's honesty gates (dogfood 2026-07-19: the completion
// banner "改动已应用——查看差异后标记完成" showed 2s after goal submit — leaked from ANOTHER
// run via workspace-level status — stayed up during the whole run, and survived acceptance).

const acceptingOverview = {
  ok: true,
  workflow: { can_review: false, can_accept: true, workflow_state: "ready_for_accept" },
} as unknown as OverviewPayload;

function runDetailWith(overrides: Record<string, unknown>): RunDetailPayload {
  return {
    ok: true,
    run_id: "run-test-0001",
    decision_requests: [],
    main_action: {},
    run_loop_summary: { runtime_progress: { loop: {} } },
    ...overrides,
  } as unknown as RunDetailPayload;
}

const noEvents: StudioEvent[] = [];

describe("runtimeSnapshotActionable honesty gates", () => {
  it("gate 1: while the session's job runs, workspace-level can_accept must not surface the bar", () => {
    expect(
      runtimeSnapshotActionable(acceptingOverview, runDetailWith({}), noEvents, true),
    ).toBe(false);
  });

  it("gate 1 exception: a pending decision card still surfaces mid-run", () => {
    const detail = runDetailWith({
      decision_requests: [{ decision_id: "dp-1", options: [{ option_id: "a" }] }],
    });
    expect(runtimeSnapshotActionable(acceptingOverview, detail, noEvents, true)).toBe(true);
  });

  it("gate 2: without session-scoped run evidence, another run's can_accept is not trusted", () => {
    // The t=2s lie: brand-new session, its own run not yet created, workspace status still
    // points at the previous session's completed run.
    expect(runtimeSnapshotActionable(acceptingOverview, null, noEvents, false)).toBe(false);
  });

  it("gate 3: an accepted run is terminal — no accept affordance is re-offered", () => {
    const detail = runDetailWith({
      run_loop_summary: { workflow_state: "accepted", runtime_progress: { loop: {} } },
    });
    expect(runtimeSnapshotActionable(acceptingOverview, detail, noEvents, false)).toBe(false);
  });

  it("still actionable: session run finished (not accepted), workspace offers accept", () => {
    const detail = runDetailWith({
      run_loop_summary: {
        workflow_state: "ready_for_accept",
        runtime_progress: { loop: { exit_reason: "completed" } },
      },
    });
    expect(runtimeSnapshotActionable(acceptingOverview, detail, noEvents, false)).toBe(true);
  });
});

describe("sessionWorkflowState", () => {
  it("reads the session's own run_loop_summary, falling back to final_report_summary", () => {
    expect(
      sessionWorkflowState(runDetailWith({ run_loop_summary: { workflow_state: "Accepted" } })),
    ).toBe("accepted");
    expect(
      sessionWorkflowState(
        runDetailWith({
          run_loop_summary: {},
          final_report_summary: { workflow_state: "blocked" },
        }),
      ),
    ).toBe("blocked");
    expect(sessionWorkflowState(null)).toBe("");
  });
});
