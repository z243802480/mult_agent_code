// G4 评论即指令 — component behaviour: the per-line affordance carries a correctly anchored
import { fakeStorage } from "../testing/fakeStorage";
// comment, pending comments render under their rows, and the tray routes the batched message
// through the right existing channel (steer while running / new turn when idle / honestly blocked).
// The test harness renders static markup (no jsdom), so anchoring + routing are verified via the
// exported pure functions and the rendered HTML.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { DiffPreview, rowAnchor } from "./DiffPreview";
import { DiffCommentTray, pickCommentChannel } from "./DiffCommentTray";
import { addDiffComment, setDiffCommentSession, type DiffComment } from "../session/diffComments";

const SAMPLE_DIFF = [
  "diff --git a/src/app.ts b/src/app.ts",
  "--- a/src/app.ts",
  "+++ b/src/app.ts",
  "@@ -1,3 +1,4 @@",
  " const a = 1;",
  "+const b = 2;",
  " const c = 3;",
].join("\n");

beforeEach(() => {
  vi.stubGlobal("localStorage", fakeStorage());
  setDiffCommentSession("__reset__");
  setDiffCommentSession("session-test");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("rowAnchor — comment anchoring rules", () => {
  it("anchors added and context lines on the NEW line number", () => {
    expect(rowAnchor({ kind: "add", text: "+const b = 2;", newNo: 2 }, "a.ts")).toEqual({
      file: "a.ts",
      line: 2,
      side: "new",
      excerpt: "+const b = 2;",
    });
    expect(
      rowAnchor({ kind: "context", text: " const a = 1;", oldNo: 1, newNo: 1 }, "a.ts"),
    ).toEqual({ file: "a.ts", line: 1, side: "new", excerpt: " const a = 1;" });
  });

  it("anchors deleted lines on the OLD line number and refuses meta/hunk rows", () => {
    expect(rowAnchor({ kind: "del", text: "-gone", oldNo: 7 }, "a.ts")).toEqual({
      file: "a.ts",
      line: 7,
      side: "old",
      excerpt: "-gone",
    });
    expect(rowAnchor({ kind: "hunk", text: "@@ -1 +1 @@" }, "a.ts")).toBeNull();
    expect(rowAnchor({ kind: "meta", text: "diff --git" }, "a.ts")).toBeNull();
  });
});

describe("DiffPreview comment affordance", () => {
  it("renders per-line add buttons only when commenting is wired", () => {
    const withComments = renderToStaticMarkup(
      <DiffPreview path="src/app.ts" diff={SAMPLE_DIFF} onAddComment={() => {}} />,
    );
    expect(withComments).toContain("对第 2 行添加评论");
    const readOnly = renderToStaticMarkup(<DiffPreview path="src/app.ts" diff={SAMPLE_DIFF} />);
    expect(readOnly).not.toContain("添加评论");
  });

  it("renders pending comments under the diff with a remove affordance", () => {
    const pending: DiffComment[] = [
      {
        id: "c-1",
        file: "src/app.ts",
        line: 2,
        side: "new",
        excerpt: "+const b = 2;",
        text: "这里要写注释",
      },
    ];
    const html = renderToStaticMarkup(
      <DiffPreview
        path="src/app.ts"
        diff={SAMPLE_DIFF}
        comments={pending}
        onAddComment={() => {}}
        onRemoveComment={() => {}}
      />,
    );
    expect(html).toContain("这里要写注释");
    expect(html).toContain("删除这条评论");
  });
});

describe("pickCommentChannel — submit routing", () => {
  it("idle → new turn; running with steer → steer; running with steer opted out → blocked", () => {
    expect(pickCommentChannel(false, true, true)).toBe("send");
    expect(pickCommentChannel(false, false, false)).toBe("send");
    expect(pickCommentChannel(true, true, true)).toBe("steer");
    expect(pickCommentChannel(true, false, true)).toBe("blocked");
    expect(pickCommentChannel(true, true, false)).toBe("blocked");
  });
});

describe("DiffCommentTray", () => {
  it("renders nothing while no comments are pending", () => {
    expect(
      renderToStaticMarkup(<DiffCommentTray isRunning={false} midRunSteer onSend={vi.fn()} />),
    ).toBe("");
  });

  it("shows the batch with an honest turn-boundary label while running", () => {
    addDiffComment({ file: "src/app.ts", line: 2, side: "new", excerpt: "+b" }, "改用常量");
    const html = renderToStaticMarkup(
      <DiffCommentTray isRunning midRunSteer onSteer={vi.fn()} onSend={vi.fn()} />,
    );
    expect(html).toContain("1 条 diff 行评论待提交");
    expect(html).toContain("提交 · 下一轮生效");
  });

  it("disables submit with an honest reason when running and steer is opted out", () => {
    addDiffComment({ file: "src/app.ts", line: 2, side: "new", excerpt: "+b" }, "改用常量");
    const html = renderToStaticMarkup(
      <DiffCommentTray isRunning midRunSteer={false} onSend={vi.fn()} />,
    );
    expect(html).toContain("disabled");
    expect(html).toContain("未开启中途插话");
  });
});
