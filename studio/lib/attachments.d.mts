// Types for lib/attachments.mjs so the TS unit tests can import the real implementation instead of
// re-stating its logic in a fixture that could drift from it.

export declare const ATTACHMENT_EXTENSIONS: Record<string, string>;
export declare const MAX_ATTACHMENT_BYTES: number;

export declare function sniffImageType(buffer: Buffer | null | undefined): string;

export declare function attachmentRelPath(sessionId: string, buffer: Buffer, mime: string): string;

export declare function saveAttachment(args: {
  workspace: string;
  sessionId: string;
  buffer: Buffer;
}): Promise<{ ok: boolean; path?: string; mime?: string; bytes?: number; error?: string }>;

export declare function resolveAttachmentRequest(
  workspace: string,
  relative: string | null | undefined,
): string;

export declare function attachmentMimeFor(relative: string): string;

export declare function sanitizeAttachmentPaths(sessionId: string, values: unknown): string[];
