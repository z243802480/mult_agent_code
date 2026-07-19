import { describe, expect, it } from "vitest";
import { buildRunNarrative } from "./narrative";
import type { StudioEvent } from "./types";

// F4 (dogfood run-20260719-0001): pure runtime persistence/setup bookkeeping ("Cost report written",
// "GoalSpec file written", …) was emitted at display_level="main" and surfaced on the Chinese thread as
// projected titles ("已写出成本报告"). CC-class tools never show "wrote cost report" up front — those
// belong in the Inspector. buildRunNarrative must drop them while keeping user-meaningful milestones.

function evt(partial: Partial<StudioEvent>): StudioEvent {
  return {
    event_id: `e-${Math.random().toString(16).slice(2)}`,
    type: "message",
    status: "completed",
    created_at: "2026-07-19T14:58:06.000Z",
    ...partial,
  } as StudioEvent;
}

describe("buildRunNarrative — bookkeeping suppression (F4)", () => {
  it("drops a main-marked persistence milestone (matched on RAW English title)", () => {
    const { steps } = buildRunNarrative([
      evt({ title: "Cost report written", transcript_kind: "file_change", display_level: "main" }),
    ]);
    expect(steps).toHaveLength(0);
  });

  it("keeps user-meaningful milestones beside a suppressed one", () => {
    const { steps } = buildRunNarrative([
      evt({ title: "GoalSpec file written", transcript_kind: "file_change", display_level: "main" }),
      evt({
        title: "我已实现 stats 子命令。",
        transcript_kind: "assistant_message",
        display_level: "main",
      }),
      evt({ title: "Cost report written", transcript_kind: "file_change", display_level: "main" }),
    ]);
    expect(steps).toHaveLength(1);
    expect(steps[0].kind).toBe("narration");
  });

  it("honors display_level: inspector rows leaking via the raw events path are dropped", () => {
    // The session-owns-output path feeds raw events.jsonl straight into buildRunNarrative, so an
    // inspector-level row would otherwise appear in the completed thread (the live view already drops
    // it). buildRunNarrative must match that behavior.
    const { steps } = buildRunNarrative([
      evt({ title: "Build task plan", transcript_kind: "tool_use", display_level: "inspector" }),
      evt({
        title: "正在读取 taskman.py",
        transcript_kind: "assistant_message",
        display_level: "main",
      }),
    ]);
    expect(steps).toHaveLength(1);
    expect(steps[0].title).toContain("taskman.py");
  });

  it("passes events through unchanged when display_level is absent", () => {
    const { steps } = buildRunNarrative([
      evt({ title: "我先创建 stats.py", transcript_kind: "assistant_message" }),
    ]);
    expect(steps).toHaveLength(1);
  });
});
