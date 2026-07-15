import { describe, expect, it } from "vitest";
import { gitUnavailableText } from "./DiffFileList";

describe("gitUnavailableText — no English leak in the Changes pane", () => {
  it("localizes the common 'not a git repository' reason with an actionable hint", () => {
    expect(gitUnavailableText("not a git repository")).toBe(
      "当前工作区还不是 Git 仓库——改动审查需要先在此目录执行 git init。",
    );
  });

  it("falls back to a Chinese message when no reason is given", () => {
    expect(gitUnavailableText(null)).toBe("该工作区不支持 Git。");
    expect(gitUnavailableText("")).toBe("该工作区不支持 Git。");
  });

  it("passes a genuine git stderr through as diagnostic (rare, not the common leak)", () => {
    expect(gitUnavailableText("fatal: detected dubious ownership")).toBe(
      "fatal: detected dubious ownership",
    );
  });
});
