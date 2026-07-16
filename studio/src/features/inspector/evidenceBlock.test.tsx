// G11 分组/批量展开 — the honesty core: truncation is DISCLOSED ("显示全部 N 条" instead of a
// silent slice) and the filter searches the ENTIRE group (the old code filtered a pre-sliced tail,
// so a match older than the last 8 entries was quietly invisible).
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceBlock } from "./EvidenceExplorer";
import type { AnyRecord } from "../../types";

// The needle lives in hook_name because the hook line renders as "hook_name task_id" —
// the filter matches the rendered line, exactly what a user sees and types against.
const items: AnyRecord[] = Array.from({ length: 12 }, (_, i) => ({
  hook_name: i === 0 ? "earliest-needle" : `hook-${i + 1}`,
  task_id: `task-${i + 1}`,
  summary: `第 ${i + 1} 次触发`,
}));

const base = {
  title: "运行时 Hook",
  kind: "hook",
  selectedKey: "",
  onPick: vi.fn(),
};

describe("EvidenceBlock (G11)", () => {
  it("shows the latest N with the truncation disclosed, never a silent slice", () => {
    const html = renderToStaticMarkup(<EvidenceBlock {...base} items={items} filter="" />);
    expect(html).toContain("显示全部 12 条");
    expect(html).toContain("hook-12");
    expect(html).toContain("hook-5");
    // The oldest entries are truncated out of view — but the count says so.
    expect(html).not.toContain("hook-1 ");
    expect(html).toContain("(12)");
  });

  it("renders everything when the list fits — no toggle noise", () => {
    const html = renderToStaticMarkup(
      <EvidenceBlock {...base} items={items.slice(0, 3)} filter="" />,
    );
    expect(html).not.toContain("显示全部");
    expect(html).toContain("(3)");
  });

  it("filter searches ALL entries of the group, not just the visible tail", () => {
    const html = renderToStaticMarkup(
      <EvidenceBlock {...base} items={items} filter="earliest-needle" />,
    );
    expect(html).toContain("earliest-needle");
    expect(html).toContain("(1/12)");
    // Matches are never re-truncated behind a toggle.
    expect(html).not.toContain("显示全部");
  });

  it("hides the whole group when the filter matches nothing (declutter)", () => {
    expect(
      renderToStaticMarkup(<EvidenceBlock {...base} items={items} filter="zzz-no-match" />),
    ).toBe("");
  });
});
