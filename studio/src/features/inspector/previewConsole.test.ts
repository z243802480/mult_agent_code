import { describe, expect, it } from "vitest";
import {
  DEVICE_PRESETS,
  isPreviewErrorMessage,
  MAX_PREVIEW_ERRORS,
  pushPreviewError,
} from "./previewConsole";

describe("isPreviewErrorMessage — only the injected client's envelope is trusted", () => {
  it("accepts the exact envelope and rejects everything else", () => {
    expect(isPreviewErrorMessage({ __asteriaPreview: "error", message: "boom" })).toBe(true);
    expect(isPreviewErrorMessage({ __asteriaPreview: "reload" })).toBe(false);
    expect(isPreviewErrorMessage({ message: "boom" })).toBe(false);
    expect(isPreviewErrorMessage("boom")).toBe(false);
    expect(isPreviewErrorMessage(null)).toBe(false);
    expect(isPreviewErrorMessage({ __asteriaPreview: "error", message: 42 })).toBe(false);
  });
});

describe("pushPreviewError — bounded, dedupes immediate repeats", () => {
  it("appends, ignores blanks, collapses an immediate duplicate", () => {
    let errors: string[] = [];
    errors = pushPreviewError(errors, "TypeError: x is undefined");
    errors = pushPreviewError(errors, "   ");
    errors = pushPreviewError(errors, "TypeError: x is undefined");
    errors = pushPreviewError(errors, "第二个错误");
    expect(errors).toEqual(["TypeError: x is undefined", "第二个错误"]);
  });

  it("keeps only the latest MAX entries (a render-loop error storm stays bounded)", () => {
    let errors: string[] = [];
    for (let i = 0; i < MAX_PREVIEW_ERRORS + 10; i++) {
      errors = pushPreviewError(errors, `错误 ${i}`);
    }
    expect(errors).toHaveLength(MAX_PREVIEW_ERRORS);
    expect(errors[errors.length - 1]).toBe(`错误 ${MAX_PREVIEW_ERRORS + 9}`);
  });
});

describe("DEVICE_PRESETS", () => {
  it("carries the mainstream trio plus fit-to-panel", () => {
    expect(DEVICE_PRESETS.map((p) => p.width)).toEqual([null, 375, 768, 1280]);
  });
});
