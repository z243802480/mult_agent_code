import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { AnyRecord, NarrativeStep, StudioEvent } from "../../types";
import { ToolCallCard, toolResultOutput } from "./ToolCallCard";

function ev(partial: Partial<StudioEvent> & { data?: AnyRecord }): StudioEvent {
  return {
    event_id: "e",
    session_id: "s",
    type: "tool_end",
    status: "completed",
    created_at: "2026-07-15T10:00:00.000Z",
    ...partial,
  } as StudioEvent;
}

function step(events: StudioEvent[]): NarrativeStep {
  return {
    id: "step",
    kind: "tool",
    label: "tool",
    title: "",
    summary: "",
    status: "completed",
    events,
    defaultOpen: false,
  } as NarrativeStep;
}

describe("toolResultOutput", () => {
  it("prefers streamed content_delta when present", () => {
    const s = step([
      ev({ content_delta: "streamed line 1\n" }),
      ev({ content_delta: "streamed line 2", data: { stdout: "IGNORED" } }),
    ]);
    expect(toolResultOutput(s)).toBe("streamed line 1\nstreamed line 2");
  });

  it("falls back to data.stdout when nothing streamed (the $ pytest / 完成 case)", () => {
    const s = step([
      ev({ command: ["pytest", "-q"], data: {} }),
      ev({ data: { stdout: "3 passed in 0.12s\n", stderr: "" } }),
    ]);
    expect(toolResultOutput(s)).toBe("3 passed in 0.12s");
  });

  it("labels stderr and appends a truncation hint pointing at the Inspector", () => {
    const s = step([
      ev({ data: { stdout: "partial out", stderr: "a warning", stdout_truncated: true } }),
    ]);
    const out = toolResultOutput(s);
    expect(out).toContain("partial out");
    expect(out).toContain("stderr:\na warning");
    expect(out).toContain("输出已截断");
  });

  it("returns stderr alone when stdout is empty (a failing command)", () => {
    const s = step([ev({ data: { stdout: "", stderr: "Traceback: boom" } })]);
    expect(toolResultOutput(s)).toBe("stderr:\nTraceback: boom");
  });

  it("returns empty string when the step carries no output at all", () => {
    expect(toolResultOutput(step([ev({ data: { ok: true } })]))).toBe("");
    expect(toolResultOutput(step([ev({})]))).toBe("");
  });

  it("ignores non-string stdout/stderr instead of coercing objects into the body", () => {
    const s = step([ev({ data: { stdout: { nested: "x" }, stderr: 42 } as AnyRecord })]);
    expect(toolResultOutput(s)).toBe("");
  });
});

describe("ToolCallCard wiring (data.stdout makes a shell card expandable)", () => {
  it("renders an expandable card (no data-static) when only data.stdout carries the output", () => {
    const s = step([
      ev({ type: "tool_start", command: ["pytest", "-q"], data: {} }),
      ev({ type: "tool_end", data: { stdout: "3 passed in 0.12s\n" } }),
    ]);
    const html = renderToStaticMarkup(<ToolCallCard step={s} />);
    expect(html).not.toContain('data-static="true"'); // expandable, not a dead label
  });

  it("renders a static card (data-static) when the step has no output to show", () => {
    const s = step([ev({ type: "tool_end", data: { ok: true } })]);
    const html = renderToStaticMarkup(<ToolCallCard step={s} />);
    expect(html).toContain('data-static="true"');
  });

  it("suppresses expandability when showOutput is false (history turns stay label-only)", () => {
    const s = step([ev({ type: "tool_end", data: { stdout: "output here" } })]);
    const html = renderToStaticMarkup(<ToolCallCard step={s} showOutput={false} />);
    expect(html).toContain('data-static="true"');
  });
});
