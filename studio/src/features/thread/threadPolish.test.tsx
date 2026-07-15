import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { ToolCallCard } from "./ToolCallCard";
import { PendingTurn } from "./ConversationTurn";

function toolStep(status: string): NarrativeStepType {
  return {
    id: "s1",
    kind: "tool",
    label: "工具",
    title: "写入 x.py",
    summary: "",
    status,
    events: [{ event_id: "e1", command: [] }],
  } as unknown as NarrativeStepType;
}

describe("ToolCallCard status label (no English enum leak)", () => {
  it("maps queued to a Chinese label", () => {
    const html = renderToStaticMarkup(
      React.createElement(ToolCallCard, { step: toolStep("queued") }),
    );
    expect(html).toContain("排队中");
    // The raw enum may appear as a CSS class, but never as the visible chip TEXT.
    expect(html).not.toContain(">queued<");
  });

  it("shows no status chip for an unknown status rather than leaking the raw enum", () => {
    const html = renderToStaticMarkup(
      React.createElement(ToolCallCard, { step: toolStep("cancelled") }),
    );
    // No status chip is rendered at all (statusLabel is empty) — the raw enum never becomes text.
    expect(html).not.toContain("toolCardStatus");
    expect(html).not.toContain(">cancelled<");
    // The card still renders its action label.
    expect(html).toContain("写入 x.py");
  });

  it("maps completed/running/failed to Chinese", () => {
    expect(
      renderToStaticMarkup(React.createElement(ToolCallCard, { step: toolStep("completed") })),
    ).toContain("完成");
    expect(
      renderToStaticMarkup(React.createElement(ToolCallCard, { step: toolStep("failed") })),
    ).toContain("失败");
  });
});

describe("PendingTurn reflects the chosen mode", () => {
  const render = (mode: string) =>
    renderToStaticMarkup(
      React.createElement(PendingTurn, { message: "做点事", mode, startedAt: 0 }),
    );

  it("shows the explicit mode's phase so a deliberate choice is confirmed", () => {
    expect(render("plan")).toContain("规划中");
    expect(render("run")).toContain("执行中");
    expect(render("chat")).toContain("对话中");
  });

  it("stays honest for auto (routing undecided) with the neutral phrase", () => {
    const html = render("auto");
    expect(html).toContain("思考中");
    // The user's message still shows optimistically.
    expect(html).toContain("做点事");
  });
});
