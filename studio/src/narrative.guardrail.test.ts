import { describe, expect, it } from "vitest";
import { buildRunNarrative, toNarrativeEvents } from "./narrative";
import type { StudioEvent } from "./types";

// B5: the continuity guardrail held the loop open — the model tried to finish, an expected artifact
// was still missing, and the run kept going. This is the ONE event that answers "why is it still
// running", so it must survive the thread's scaffolding filter and land as a first-class card.
//
// Both obvious encodings fail, which is why `guardrail` exists as its own kind:
//   transcript_kind "verification" → folds away into the collapsed process detail
//   transcript_kind "repair" + non-failed status → dropped as loop bookkeeping (narrative.ts)
// so the card is recognised by a STABLE STRUCTURAL MARKER (data.held_open), never by title text.
function heldOpenCard(): StudioEvent {
  return {
    event_id: "upe-0007",
    type: "message",
    status: "running",
    phase: "execute",
    title: "还差产出,继续做",
    summary: "模型想收尾,但这些交付物还没出现:src/notes.py。已让它继续完成并验证。",
    transcript_kind: "verification",
    display_level: "main",
    created_at: "2026-07-14T10:00:00Z",
    data: { held_open: true, hook_name: "pre_final", missing_artifacts: ["src/notes.py"] },
  } as unknown as StudioEvent;
}

describe("held-open guardrail on the main thread", () => {
  it("survives the scaffolding filter", () => {
    const kept = toNarrativeEvents([heldOpenCard()]);
    expect(kept).toHaveLength(1);
  });

  it("becomes a first-class guardrail step that opens by default", () => {
    const { steps } = buildRunNarrative([heldOpenCard()]);
    const guardrail = steps.find((step) => step.kind === "guardrail");
    expect(guardrail).toBeDefined();
    expect(guardrail?.defaultOpen).toBe(true);
    expect(guardrail?.summary).toContain("src/notes.py");
  });

  it("does not turn an ordinary verification row into a guardrail", () => {
    const plain = {
      ...heldOpenCard(),
      title: "核对结果",
      data: {},
    } as unknown as StudioEvent;
    const { steps } = buildRunNarrative([plain]);
    expect(steps.some((step) => step.kind === "guardrail")).toBe(false);
  });
});
