import { describe, expect, it } from "vitest";
import type { StudioSession } from "../../types";
import { cleanSessionTitle, sessionPreview } from "./sessionListUtils";

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

  it("falls back on a wholesale misdecode even when a stray ideograph and digits survive (the reported sidebar 乱码)", () => {
    // Built from the EXACT codepoints of a real corrupted test_project session.json
    // (session-1784105086265, goal "…回答:1+1等于几?" via a non-UTF-8 console). U+FFFD (0xFFFD)
    // strips out, leaving a coincidental "仰" (0x4EF0) + Cyrillic/Arabic debris (0x04BB, 0x0634,
    // 0x06BC) + "1+1". The OLD guard kept it because a CJK char survived; the stray-script
    // fingerprint (2+ of those foreign letters) now sends it to the fallback.
    const real = String.fromCharCode(
      0xfffd,
      0xfffd,
      0x04bb,
      0xfffd,
      0x4ef0,
      0xfffd,
      0x0634,
      0xfffd,
      0x3a,
      0x31,
      0x2b,
      0x31,
      0xfffd,
      0xfffd,
      0x06bc,
    );
    expect(cleanSessionTitle(real)).toBe("未命名会话");
    // Real shape with no readable content at all (session-1783953260709): IPA + Cyrillic + U+FFFD.
    const real2 = String.fromCharCode(
      0x02b5,
      0xfffd,
      0xfffd,
      0x04bb,
      0xfffd,
      0xfffd,
      0xfffd,
      0x01aa,
    );
    expect(cleanSessionTitle(real2)).toBe("未命名会话");
  });

  it("still salvages a long valid Chinese title that only lost its trailing char", () => {
    // Shape (1) must NOT be caught by the stray-script fallback: no foreign-script debris, all CJK.
    expect(cleanSessionTitle("请分点详细解释这道题" + String.fromCharCode(0xfffd))).toBe(
      "请分点详细解释这道题",
    );
  });

  it("hides a corrupt goal_preview instead of leaking mojibake into the subtitle/tooltip", () => {
    const corruptPreview = String.fromCharCode(
      0xfffd,
      0xfffd,
      0x04bb,
      0xfffd,
      0x4ef0,
      0xfffd,
      0x0634,
      0xfffd,
      0x06bc,
    );
    expect(sessionPreview({ goal_preview: corruptPreview } as StudioSession)).toBe("");
    // A clean preview passes through unchanged.
    expect(sessionPreview({ goal_preview: "用一句话说明素数的定义。" } as StudioSession)).toBe(
      "用一句话说明素数的定义。",
    );
    expect(sessionPreview({ goal_preview: "" } as StudioSession)).toBe("");
  });

  it("returns the unnamed fallback for an empty or whitespace-only title", () => {
    expect(cleanSessionTitle("")).toBe("未命名会话");
    expect(cleanSessionTitle("   ")).toBe("未命名会话");
  });

  it("never throws on a missing title — untitled sessions carry no title field", () => {
    // The header crashed the whole app on cleanSessionTitle(undefined) when this guard was first
    // wired there (2026-07-16); a display guard must be total.
    expect(cleanSessionTitle(undefined)).toBe("未命名会话");
    expect(cleanSessionTitle(null)).toBe("未命名会话");
  });

  it("does not treat a legitimate title with punctuation as mojibake", () => {
    expect(cleanSessionTitle("把这些笔记整理成一页 PRD")).toBe("把这些笔记整理成一页 PRD");
  });
});
