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

describe("R2-5 verdict: adjacent narration/closing already render as ONE card", () => {
  // Verdict from render-path verification (narrative.ts shouldGroup's generic phase-equality
  // fallback): consecutive assistant_message events in the same phase were ALREADY grouped into a
  // single step whose visible text is the LAST event's — the run-20260720-0001 "模型叙述 + 模型收尾
  // same text" observation existed only in the raw event stream, never on the rendered thread.
  // These tests pin that truth so it cannot silently regress; no fuzzy dedupe was added.
  const narration = (text: string, at: string) =>
    ({
      event_id: `upe-${at}`,
      type: "assistant_delta",
      status: "completed",
      title: "模型叙述",
      summary: text,
      transcript_kind: "assistant_message",
      display_level: "main",
      created_at: at,
      data: {},
    }) as unknown as StudioEvent;
  const closing = (text: string, at: string) => ({
    ...narration(text, at),
    title: "模型收尾",
  });

  it("the real dogfood pair (re-worded by one character) renders as one card carrying the CLOSING text", () => {
    const steps = buildRunNarrative([
      narration("我将先读取现有的 taskman.py 和 test_taskman.py 完整内容以了解现有结构。", "t1"),
      closing("我先读取现有的 taskman.py 和 test_taskman.py 完整内容以了解现有结构。", "t2"),
    ]).steps;
    const narrations = steps.filter((s) => s.kind === "narration");
    expect(narrations).toHaveLength(1);
    expect(narrations[0].summary).toContain("我先读取");
    expect(narrations[0].summary).not.toContain("我将先读取");
  });

  it("different-phase narration messages stay separate cards", () => {
    const steps = buildRunNarrative([
      narration("我先创建 clamp.py，写入阈值逻辑。", "t1"),
      { ...closing("任务完成：clamp.py 已就绪。", "t2"), phase: "review" },
    ]).steps;
    expect(steps.filter((s) => s.kind === "narration")).toHaveLength(2);
  });
});
