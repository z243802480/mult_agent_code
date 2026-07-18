import { describe, expect, it } from "vitest";
import type { StudioEvent } from "../types";
import {
  AI_REVIEW_SENTINEL,
  buildAiReviewPrompt,
  isCleanVerdict,
  latestAiReview,
  NO_FINDINGS_MARKER,
  parseReviewFindings,
} from "./aiReview";

const event = (over: Partial<StudioEvent>): StudioEvent =>
  ({
    event_id: `e-${Math.abs(JSON.stringify(over).length)}-${over.type}`,
    session_id: "s1",
    type: "user_message",
    status: "completed",
    title: "",
    summary: "",
    ...over,
  }) as StudioEvent;

describe("buildAiReviewPrompt", () => {
  it("carries the sentinel, the strict output format, and the fenced diffs", () => {
    const prompt = buildAiReviewPrompt([{ path: "calc.py", diff: "@@ -1 +1 @@\n+x = 1" }]);
    expect(prompt.startsWith(AI_REVIEW_SENTINEL)).toBe(true);
    expect(prompt).toContain("文件路径:行号 — 问题说明");
    expect(prompt).toContain(NO_FINDINGS_MARKER);
    expect(prompt).toContain("### calc.py");
    expect(prompt).toContain("```diff");
    expect(prompt).toContain("不要修改任何文件");
    expect(prompt).not.toContain("只截取了一部分");
  });

  it("states truncation honestly — the verdict must not claim unseen coverage", () => {
    const prompt = buildAiReviewPrompt([{ path: "a.ts", diff: "+1" }], { truncated: true });
    expect(prompt).toContain("只截取了一部分");
  });
});

describe("latestAiReview", () => {
  const request = event({ type: "user_message", content_delta: `${AI_REVIEW_SENTINEL}评审这些` });

  it("returns none when the transcript has no review round", () => {
    expect(latestAiReview([event({ type: "user_message", content_delta: "普通消息" })])).toEqual({
      status: "none",
      answer: null,
    });
  });

  it("is pending after the request until a final answer lands, then answered with the verdict", () => {
    expect(latestAiReview([request]).status).toBe("pending");
    const answered = latestAiReview([
      request,
      event({ type: "final_answer", content_delta: "calc.py:9 — 问题" }),
    ]);
    expect(answered).toEqual({ status: "answered", answer: "calc.py:9 — 问题" });
  });

  it("does not mistake an interleaved side-ask answer (or error) for the review verdict", () => {
    const sideAnswer = event({
      type: "final_answer",
      content_delta: "侧聊的答案",
      display_level: "side",
    });
    const interleaved = latestAiReview([request, sideAnswer]);
    expect(interleaved.status).toBe("pending");

    const sideError = event({ type: "error", ui_intent: "side_chat" });
    expect(latestAiReview([request, sideError]).status).toBe("pending");

    const resolved = latestAiReview([
      request,
      sideAnswer,
      event({ type: "final_answer", content_delta: "calc.py:9 — 问题" }),
    ]);
    expect(resolved).toEqual({ status: "answered", answer: "calc.py:9 — 问题" });
  });

  it("marks the round failed on an error with no answer, and always uses the LATEST round", () => {
    expect(latestAiReview([request, event({ type: "error" })]).status).toBe("failed");
    const twoRounds = latestAiReview([
      request,
      event({ type: "final_answer", content_delta: "旧结论" }),
      event({ type: "user_message", content_delta: `${AI_REVIEW_SENTINEL}再评一次` }),
    ]);
    expect(twoRounds.status).toBe("pending");
  });
});

describe("parseReviewFindings", () => {
  const known = ["calc.py", "src/util.ts"];

  it("parses `file:line — note` lines in several tolerated shapes", () => {
    const answer = [
      "calc.py:9 — mul 没有处理非数字输入",
      "- `src/util.ts:12` - 变量遮蔽了外层作用域",
      "2. calc.py:17：除零风险",
      "这一行是普通散文，不是发现。",
    ].join("\n");
    expect(parseReviewFindings(answer, known)).toEqual([
      { file: "calc.py", line: 9, note: "mul 没有处理非数字输入" },
      { file: "src/util.ts", line: 12, note: "变量遮蔽了外层作用域" },
      { file: "calc.py", line: 17, note: "除零风险" },
    ]);
  });

  it("drops findings for files that are not in the current diff (anti-hallucination anchor)", () => {
    expect(parseReviewFindings("ghost.py:3 — 不存在的文件", known)).toEqual([]);
  });

  it("dedupes identical findings and tolerates backslash/suffix path shapes", () => {
    const answer = ["util.ts:12 — 同一条", "src\\util.ts:12 — 同一条"].join("\n");
    expect(parseReviewFindings(answer, known)).toEqual([
      { file: "src/util.ts", line: 12, note: "同一条" },
    ]);
  });
});

describe("isCleanVerdict", () => {
  it("recognises the explicit clean marker and nothing else", () => {
    expect(isCleanVerdict(`${NO_FINDINGS_MARKER}。`)).toBe(true);
    expect(isCleanVerdict("有两个问题")).toBe(false);
    expect(isCleanVerdict(null)).toBe(false);
  });
});
