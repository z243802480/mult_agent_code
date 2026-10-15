import { describe, expect, it } from "vitest";
import {
  attachmentRelPath,
  resolveAttachmentRequest,
  sanitizeAttachmentPaths,
  sniffImageType,
} from "../../lib/attachments.mjs";

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);
const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff]), Buffer.alloc(9)]);

describe("sniffImageType", () => {
  it("identifies the formats the runtime accepts", () => {
    expect(sniffImageType(PNG)).toBe("image/png");
    expect(sniffImageType(JPEG)).toBe("image/jpeg");
    expect(sniffImageType(Buffer.concat([Buffer.from("GIF89a"), Buffer.alloc(6)]))).toBe(
      "image/gif",
    );
    expect(
      sniffImageType(Buffer.concat([Buffer.from("RIFF"), Buffer.alloc(4), Buffer.from("WEBP")])),
    ).toBe("image/webp");
  });

  it("rejects content that is not an image, whatever it claims to be", () => {
    // The sniff decides the stored extension and the MIME it is later served with, so a caller
    // naming an executable "shot.png" must not get a stored .png back.
    // A real DOS/PE header, written as bytes: the literal string form put raw NULs in this
    // source (git then treats the whole test file as binary and can never diff it) and
    // Buffer.from(str) would UTF-8 encode the 0x90 into two bytes anyway, so it was not the
    // header it claimed to be.
    const dosExecutable = Buffer.from([
      0x4d, 0x5a, 0x90, 0x00, 0x03, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00,
    ]);
    expect(sniffImageType(dosExecutable)).toBe("");
    expect(sniffImageType(Buffer.from("<script>alert(1)</script>"))).toBe("");
  });

  it("rejects buffers too short to identify", () => {
    expect(sniffImageType(Buffer.from([0x89, 0x50]))).toBe("");
    expect(sniffImageType(null)).toBe("");
  });
});

describe("attachmentRelPath", () => {
  it("is content addressed, so the same paste twice is one file", () => {
    expect(attachmentRelPath("s1", PNG, "image/png")).toBe(
      attachmentRelPath("s1", PNG, "image/png"),
    );
  });

  it("separates sessions and carries no caller-supplied string", () => {
    const p = attachmentRelPath("sess-1", PNG, "image/png");
    expect(p).toMatch(/^\.asteria\/attachments\/sess-1\/[a-f0-9]{16}\.png$/);
    expect(attachmentRelPath("sess-2", PNG, "image/png")).not.toBe(p);
  });
});

describe("sanitizeAttachmentPaths", () => {
  const mine = ".asteria/attachments/s1/aabbccddeeff0011.png";

  it("keeps this session's own attachments", () => {
    expect(sanitizeAttachmentPaths("s1", [mine])).toEqual([mine]);
  });

  it("rejects paths belonging to another session", () => {
    // The paths round-trip through the client, so a crafted one must not make the runtime read
    // someone else's file and hand it to the model.
    expect(sanitizeAttachmentPaths("s1", [".asteria/attachments/s2/aabbccddeeff0011.png"])).toEqual(
      [],
    );
  });

  it("rejects traversal and non-attachment paths", () => {
    expect(
      sanitizeAttachmentPaths("s1", [
        ".asteria/attachments/s1/../../../.env",
        "../../etc/passwd",
        ".env",
        "src/main.py",
      ]),
    ).toEqual([]);
  });

  it("rejects non-image extensions", () => {
    expect(sanitizeAttachmentPaths("s1", [".asteria/attachments/s1/aabbccddeeff0011.sh"])).toEqual(
      [],
    );
  });

  it("dedupes and tolerates junk input", () => {
    expect(sanitizeAttachmentPaths("s1", [mine, mine])).toEqual([mine]);
    expect(sanitizeAttachmentPaths("s1", null)).toEqual([]);
    expect(sanitizeAttachmentPaths("s1", [null, 3, ""])).toEqual([]);
  });
});

describe("resolveAttachmentRequest", () => {
  it("resolves a real attachment under the workspace", () => {
    expect(resolveAttachmentRequest("/ws", ".asteria/attachments/s1/aabbccddeeff0011.png")).toMatch(
      /aabbccddeeff0011\.png$/,
    );
  });

  it("refuses anything outside the attachment tree", () => {
    // A GET route that served arbitrary workspace paths would be a read-any-file hole.
    expect(resolveAttachmentRequest("/ws", ".env")).toBe("");
    expect(resolveAttachmentRequest("/ws", "../../etc/passwd")).toBe("");
    expect(resolveAttachmentRequest("/ws", ".asteria/memory/active_goal.json")).toBe("");
    expect(resolveAttachmentRequest("/ws", ".asteria/attachments/s1/notahash.png")).toBe("");
    expect(resolveAttachmentRequest("/ws", "")).toBe("");
  });
});
