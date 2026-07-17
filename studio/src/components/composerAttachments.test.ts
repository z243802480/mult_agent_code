import { describe, expect, it } from "vitest";
import { clipboardImages } from "./Composer";
import { turnAttachmentPaths } from "../features/thread/ConversationTurn";
import type { StudioEvent } from "../types";

function dataTransfer(items: { kind: string; type: string; file?: File | null }[]): DataTransfer {
  return {
    items: items.map((item) => ({
      kind: item.kind,
      type: item.type,
      getAsFile: () => item.file ?? null,
    })),
  } as unknown as DataTransfer;
}

const png = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "shot.png", { type: "image/png" });

describe("clipboardImages", () => {
  it("returns images pasted from the clipboard", () => {
    const files = clipboardImages(dataTransfer([{ kind: "file", type: "image/png", file: png }]));
    expect(files).toEqual([png]);
  });

  it("ignores an ordinary text paste so the browser still inserts the text", () => {
    expect(clipboardImages(dataTransfer([{ kind: "string", type: "text/plain" }]))).toEqual([]);
  });

  it("ignores non-image files", () => {
    const pdf = new File([new Uint8Array([1])], "a.pdf", { type: "application/pdf" });
    expect(clipboardImages(dataTransfer([{ kind: "file", type: "application/pdf", file: pdf }]))).toEqual(
      [],
    );
  });

  it("skips items whose getAsFile yields nothing", () => {
    expect(clipboardImages(dataTransfer([{ kind: "file", type: "image/png", file: null }]))).toEqual(
      [],
    );
  });

  it("survives a paste with no clipboard data", () => {
    expect(clipboardImages(null)).toEqual([]);
  });
});

describe("turnAttachmentPaths", () => {
  const event = (data: unknown): StudioEvent => ({ data }) as unknown as StudioEvent;

  it("reads the paths a user turn carried", () => {
    expect(turnAttachmentPaths(event({ attachments: [".asteria/attachments/s1/ab.png"] }))).toEqual([
      ".asteria/attachments/s1/ab.png",
    ]);
  });

  it("returns nothing for an ordinary message", () => {
    expect(turnAttachmentPaths(event({}))).toEqual([]);
    expect(turnAttachmentPaths(undefined)).toEqual([]);
  });

  it("drops non-string entries rather than rendering junk", () => {
    expect(turnAttachmentPaths(event({ attachments: ["ok.png", 3, null, ""] }))).toEqual(["ok.png"]);
  });
});
