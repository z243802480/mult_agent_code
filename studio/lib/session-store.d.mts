// Types for lib/session-store.mjs so the TS unit tests exercise the real implementation.

export declare function parseSessionText(raw: unknown): Record<string, unknown> | null;

export declare function writeSessionJson(file: string, session: unknown): Promise<void>;
