import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeStorage } from "../testing/fakeStorage";
import {
  addDiffComment,
  clearDiffComments,
  commentsKey,
  formatCommentsMessage,
  getDiffComments,
  loadComments,
  MAX_COMMENT_CHARS,
  MAX_COMMENTS,
  removeDiffComment,
  saveComments,
  setDiffCommentSession,
  type DiffComment,
} from "./diffComments";

const comment = (over: Partial<DiffComment> = {}): DiffComment => ({
  id: "c-1",
  file: "src/app.ts",
  line: 42,
  side: "new",
  excerpt: "+  const x = 1;",
  text: "这里应该用常量名 MAX_X",
  ...over,
});

describe("diffComments persistence", () => {
  it("round-trips comments per session and clears the key when empty", () => {
    const store = fakeStorage();
    saveComments("s1", [comment()], store);
    expect(loadComments("s1", store)).toHaveLength(1);
    expect(loadComments("s2", store)).toHaveLength(0);
    saveComments("s1", [], store);
    expect(store.dump().has(commentsKey("s1"))).toBe(false);
  });

  it("drops malformed entries and bounds count/length instead of crashing", () => {
    const store = fakeStorage();
    const junk = [
      comment(),
      { file: "", text: "no file" },
      { file: "a.ts" }, // no text
      "not-an-object",
      comment({ id: "c-2", text: "x".repeat(MAX_COMMENT_CHARS + 500) }),
    ];
    store.setItem(commentsKey("s1"), JSON.stringify(junk));
    const loaded = loadComments("s1", store);
    expect(loaded).toHaveLength(2);
    expect(loaded[1].text).toHaveLength(MAX_COMMENT_CHARS);
    // Corrupt JSON → empty, never a throw.
    store.setItem(commentsKey("s1"), "{nope");
    expect(loadComments("s1", store)).toEqual([]);
  });
});

describe("diffComments module store", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", fakeStorage());
    // Force a reload from the stubbed (empty) storage: switch away and back.
    setDiffCommentSession("__reset__");
    setDiffCommentSession("session-a");
  });

  it("add/remove/clear mutate the active session's list", () => {
    addDiffComment({ file: "a.ts", line: 3, side: "new", excerpt: "+foo" }, "改成 bar");
    addDiffComment({ file: "b.ts", line: null, side: "old", excerpt: "-baz" }, "别删这行");
    expect(getDiffComments()).toHaveLength(2);
    removeDiffComment(getDiffComments()[0].id);
    expect(getDiffComments()).toHaveLength(1);
    expect(getDiffComments()[0].file).toBe("b.ts");
    clearDiffComments();
    expect(getDiffComments()).toEqual([]);
  });

  it("ignores empty text and enforces the count cap", () => {
    addDiffComment({ file: "a.ts", line: 1, side: "new", excerpt: "" }, "   ");
    expect(getDiffComments()).toHaveLength(0);
    for (let i = 0; i < MAX_COMMENTS + 5; i++) {
      addDiffComment({ file: "a.ts", line: i, side: "new", excerpt: "" }, `第 ${i} 条`);
    }
    expect(getDiffComments()).toHaveLength(MAX_COMMENTS);
  });

  it("switching sessions swaps the visible list (comments belong to the session)", () => {
    addDiffComment({ file: "a.ts", line: 1, side: "new", excerpt: "" }, "评论 A");
    setDiffCommentSession("session-b");
    expect(getDiffComments()).toEqual([]);
    setDiffCommentSession("session-a");
    expect(getDiffComments()).toHaveLength(1);
  });
});

describe("formatCommentsMessage", () => {
  it("renders a numbered structured reference the model can act on", () => {
    const message = formatCommentsMessage([
      comment(),
      comment({
        id: "c-2",
        file: "src/util.ts",
        line: 7,
        side: "old",
        excerpt: "-  return null;",
        text: "删掉这个分支前先确认调用方",
      }),
      comment({ id: "c-3", line: null, excerpt: "", text: "整个文件加个头注释" }),
    ]);
    expect(message).toContain("请按下面这些针对当前工作区改动的行级评论修改代码：");
    expect(message).toContain("1. src/app.ts:42（修改后第 42 行）");
    expect(message).toContain("> +  const x = 1;");
    expect(message).toContain("意见：这里应该用常量名 MAX_X");
    expect(message).toContain("2. src/util.ts:7（修改前第 7 行）");
    // No line anchor → file-level comment, no dangling colon.
    expect(message).toContain("3. src/app.ts\n   意见：整个文件加个头注释");
  });
});
