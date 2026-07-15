import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InlineFileDiff } from "./InlineFileDiff";

describe("InlineFileDiff collapsed row", () => {
  it("shows a localized operation badge, the file basename, and the +/- delta", () => {
    const html = renderToStaticMarkup(
      React.createElement(InlineFileDiff, {
        path: "src/mathf.py",
        operation: "create",
        additions: 12,
        deletions: 3,
      }),
    );
    expect(html).toContain("新增"); // create -> 中文 badge, not the English enum
    expect(html).toContain("mathf.py"); // basename, not the full path in the label
    expect(html).toContain("+12");
    expect(html).toContain("-3");
    // Collapsed by default: the diff body is not rendered until expanded (lazy fetch).
    expect(html).not.toContain("inlineFileDiffBody");
  });

  it("falls back to a neutral 改动 label for an unknown operation", () => {
    const html = renderToStaticMarkup(
      React.createElement(InlineFileDiff, { path: "a/b/notes.md", operation: "weird" }),
    );
    expect(html).toContain("改动");
    expect(html).toContain("notes.md");
  });

  it("omits a zero delta rather than showing +0 / -0 noise", () => {
    const html = renderToStaticMarkup(
      React.createElement(InlineFileDiff, {
        path: "x.py",
        operation: "modify",
        additions: 5,
        deletions: 0,
      }),
    );
    expect(html).toContain("+5");
    expect(html).not.toContain("-0");
  });
});
