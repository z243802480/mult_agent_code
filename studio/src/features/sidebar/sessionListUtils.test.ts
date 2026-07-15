import { describe, expect, it } from "vitest";
import { cleanSessionTitle } from "./sessionListUtils";

describe("cleanSessionTitle — mojibake guard for legacy CLI sessions", () => {
  it("keeps a normal Chinese title untouched", () => {
    expect(cleanSessionTitle("修复失败的 CI 检查")).toBe("修复失败的 CI 检查");
  });

  it("keeps a normal English title untouched", () => {
    expect(cleanSessionTitle("Add a --version flag")).toBe("Add a --version flag");
  });

  it("recovers a good UTF-8 prefix by stripping a mangled surrogate tail (the common real shape)", () => {
    // Real test_project session: the Chinese is intact UTF-8, only the trailing "。" was lost to
    // surrogateescape bytes. Stripping the lone surrogates + U+FFFD recovers the real title cleanly.
    expect(cleanSessionTitle("用一句话说明素数的定义�\uDC80\uDC82")).toBe("用一句话说明素数的定义");
  });

  it("keeps valid astral characters (emoji) — only LONE surrogates are stripped", () => {
    // 🚀 is a valid high+low surrogate PAIR and must survive; the trailing lone surrogate is mojibake.
    expect(cleanSessionTitle("发布 🚀 计划\uDCAB")).toBe("发布 🚀 计划");
  });

  it("falls back to a clean label when the title is pure mojibake (the reported bug)", () => {
    // A GBK console's bytes decoded as UTF-8: replacement chars + a stray diacritic, no real word.
    expect(cleanSessionTitle("ʵ��")).toBe("未命名会话");
  });

  it("falls back when the decode left only replacement characters", () => {
    expect(cleanSessionTitle("���")).toBe("未命名会话");
  });

  it("partially salvages a title that still carries a real word after a failed decode", () => {
    // Half survived: the CJK word "任务" is real and worth keeping; only the mojibake byte is dropped.
    expect(cleanSessionTitle("�任务")).toBe("任务");
  });

  it("returns the unnamed fallback for an empty or whitespace-only title", () => {
    expect(cleanSessionTitle("")).toBe("未命名会话");
    expect(cleanSessionTitle("   ")).toBe("未命名会话");
  });

  it("does not treat a legitimate title with punctuation as mojibake", () => {
    expect(cleanSessionTitle("把这些笔记整理成一页 PRD")).toBe("把这些笔记整理成一页 PRD");
  });
});
