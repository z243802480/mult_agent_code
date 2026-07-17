// G17 刀二 — image attachments for the Composer.
//
// Images travel as FILES, never inside the message body: `chat-routes.submitUserGoal` runs the
// message through `redactText(String(body?.message))`, which would turn any structured payload
// into "[object Object]", and `readRequestJson` caps bodies at 64KB — smaller than most pasted
// screenshots. So the bytes get their own endpoint and the message carries only a path.
//
// Storage lives under `.asteria/attachments/<session>/` on purpose: `isSafeWorkspacePath` allows
// `.asteria/` (MemoryPanel already reads it), `fileChanges` deliberately excludes it from
// Keep/Revert (a pasted screenshot is not a code change), and preview-server already serves the
// workspace as static files with a complete image MIME table — so display needs no new channel.

import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

/** Mirrors ATTACHMENT_MIME_TYPES in chat_command.py — the runtime rejects anything else. */
export const ATTACHMENT_EXTENSIONS = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
};

/** Mirrors MAX_ATTACHMENT_BYTES in chat_command.py; rejecting here saves a doomed round trip. */
export const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

/**
 * The image type implied by the leading bytes, or "" when they match nothing we accept.
 *
 * Sniffing rather than trusting the client-declared name: the extension decides where the bytes
 * land on disk and which MIME preview-server later serves them with, so a caller-supplied ".png"
 * on non-image content must not become a stored .png.
 */
export function sniffImageType(buffer) {
  if (!buffer || buffer.length < 12) return "";
  const hex = buffer.subarray(0, 12);
  if (hex[0] === 0x89 && hex[1] === 0x50 && hex[2] === 0x4e && hex[3] === 0x47) return "image/png";
  if (hex[0] === 0xff && hex[1] === 0xd8 && hex[2] === 0xff) return "image/jpeg";
  if (hex.subarray(0, 6).toString("latin1").startsWith("GIF8")) return "image/gif";
  if (
    hex.subarray(0, 4).toString("latin1") === "RIFF" &&
    hex.subarray(8, 12).toString("latin1") === "WEBP"
  ) {
    return "image/webp";
  }
  return "";
}

/**
 * Workspace-relative path for a session's attachment, content-addressed.
 *
 * Content addressing means pasting the same screenshot twice costs one file, and the path carries
 * no caller-controlled string — the only variables are a validated session id and a hash.
 */
export function attachmentRelPath(sessionId, buffer, mime) {
  const digest = createHash("sha256").update(buffer).digest("hex").slice(0, 16);
  return `.asteria/attachments/${sessionId}/${digest}.${ATTACHMENT_EXTENSIONS[mime]}`;
}

/**
 * Persist a pasted image. Returns `{ok, path}` or `{ok:false, error}` — never throws for a bad
 * upload, because every rejection here is a user-visible message rather than a server fault.
 */
export async function saveAttachment({ workspace, sessionId, buffer }) {
  if (!buffer || !buffer.length) return { ok: false, error: "empty attachment" };
  if (buffer.length > MAX_ATTACHMENT_BYTES) {
    return {
      ok: false,
      error: `attachment is ${Math.round(buffer.length / 1024)}KB, over the ${
        MAX_ATTACHMENT_BYTES / 1024
      }KB limit`,
    };
  }
  const mime = sniffImageType(buffer);
  if (!mime) return { ok: false, error: "unsupported attachment type (images only)" };

  const relative = attachmentRelPath(sessionId, buffer, mime);
  const absolute = path.join(workspace, relative);
  await fs.mkdir(path.dirname(absolute), { recursive: true });
  // tmp + rename, not a bare writeFile. Pasting the same image twice fires two uploads at the same
  // content-addressed path; a bare write truncates the file the first upload already finished, so a
  // message sent in that window would hand the model a half-written PNG (same shape as the
  // session.json torn-file race — see session-store.mjs). The tmp name is unique per WRITE, not per
  // process: two uploads inside one server share a pid, and a shared tmp name races with itself.
  const tmp = `${absolute}.${randomUUID()}.tmp`;
  await fs.writeFile(tmp, buffer);
  try {
    await fs.rename(tmp, absolute);
  } catch (error) {
    // Windows fails concurrent renames onto one destination with EPERM (POSIX does not — found by
    // probing, not by reading). The race is benign here and only here: the destination name is a
    // hash of these exact bytes, so whoever won wrote the identical file. Confirm it landed whole
    // before calling it a win — an EPERM with no complete file is a real failure.
    await fs.rm(tmp, { force: true });
    const landed = await fs.stat(absolute).catch(() => null);
    if (!landed || landed.size !== buffer.length) throw error;
  }
  return { ok: true, path: relative, mime, bytes: buffer.length };
}

/**
 * Absolute path for serving an attachment back, or "" when the request is not one of ours.
 *
 * Deliberately NOT routed through preview-server (which does serve images already): that server is
 * a separate port whose availability under the single-port production build is unverified, and an
 * image echo that only works in dev is worse than no echo. This is a GET on the main server, so it
 * works wherever the UI works.
 */
export function resolveAttachmentRequest(workspace, relative) {
  const normalized = String(relative || "").replace(/\\/g, "/");
  if (!/^\.asteria\/attachments\/[A-Za-z0-9_.-]+\/[a-f0-9]{8,}\.(png|jpg|jpeg|gif|webp)$/i.test(normalized)) {
    return "";
  }
  if (normalized.includes("..")) return "";
  return path.join(workspace, normalized);
}

export function attachmentMimeFor(relative) {
  const ext = String(relative || "").split(".").pop()?.toLowerCase();
  for (const [mime, suffix] of Object.entries(ATTACHMENT_EXTENSIONS)) {
    if (suffix === ext || (ext === "jpeg" && suffix === "jpg")) return mime;
  }
  return "application/octet-stream";
}

/**
 * Keep only the attachment paths that this session actually owns.
 *
 * The paths make a round trip through the client, so they are untrusted input by the time they
 * come back on a message. Confining them to the session's own directory means a crafted path
 * cannot make the runtime read an arbitrary file and hand it to the model.
 */
export function sanitizeAttachmentPaths(sessionId, values) {
  const prefix = `.asteria/attachments/${sessionId}/`;
  const seen = new Set();
  const out = [];
  for (const value of Array.isArray(values) ? values : []) {
    const normalized = String(value || "").replace(/\\/g, "/");
    if (!normalized.startsWith(prefix) || normalized.includes("..")) continue;
    if (!/\.(png|jpg|jpeg|gif|webp)$/i.test(normalized)) continue;
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    out.push(normalized);
  }
  return out;
}
