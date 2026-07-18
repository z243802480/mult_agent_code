/**
 * AI 自审 (G5) — the mainstream "Review code" button: the model reviews the CURRENT workspace diff
 * and reports only high-signal problems, anchored as `file:line` so the diff view can hang each
 * finding on its file. Zero new backend protocol: the request is an ordinary chat-mode turn whose
 * message carries the diff, and the verdict is the turn's final answer. This module owns the three
 * pure pieces: prompt assembly, locating the latest review round in the transcript, and parsing
 * file-anchored findings out of the answer.
 */

import { isSideChatEvent } from "../features/sidechat/sideChatUtils";
import type { StudioEvent } from "../types";

/** Prefix of the review request message — how the transcript scan recognises a review round. */
export const AI_REVIEW_SENTINEL = "【AI 自审】";

/** The exact phrase the model is told to reply with when the diff is clean. */
export const NO_FINDINGS_MARKER = "未发现高信号问题";

export type ReviewFinding = {
  file: string;
  line: number | null;
  note: string;
};

export type AiReviewState = {
  status: "none" | "pending" | "answered" | "failed";
  answer: string | null;
};

export function buildAiReviewPrompt(
  diffs: { path: string; diff: string }[],
  { truncated = false }: { truncated?: boolean } = {},
): string {
  const lines: string[] = [
    `${AI_REVIEW_SENTINEL}请以资深工程师视角评审当前工作区的这些改动，只报高信号问题（真实 bug、逻辑风险、明显坏味道），不要泛泛的风格建议。`,
    "输出要求：",
    "- 每条问题独立一行，格式：`文件路径:行号 — 问题说明`（行号用修改后的行号）",
    `- 如果没有值得报的问题，就只回答：${NO_FINDINGS_MARKER}`,
    "- 这是一次只读评审，不要修改任何文件",
  ];
  if (truncated) {
    lines.push("（注意：改动较多，下面只截取了一部分——结论只覆盖看到的内容。）");
  }
  lines.push("");
  for (const item of diffs) {
    lines.push(`### ${item.path}`);
    lines.push("```diff");
    lines.push(item.diff.trimEnd());
    lines.push("```");
    lines.push("");
  }
  return lines.join("\n");
}

/**
 * The latest review round in this session's transcript: the LAST sentinel-prefixed user message,
 * then the first final answer that follows it. An error event with no answer marks the round
 * failed; neither yet means the review run is still in flight.
 *
 * Side-chat events are excluded up front: a side-ask answered while the review is in flight lands
 * its own final_answer in the same event stream, and without the filter that answer would be
 * mistaken for the review verdict (and its error would mark the review failed).
 */
export function latestAiReview(allEvents: StudioEvent[]): AiReviewState {
  const events = allEvents.filter((event) => !isSideChatEvent(event));
  let requestIndex = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (
      event.type === "user_message" &&
      String(event.content_delta ?? "").startsWith(AI_REVIEW_SENTINEL)
    ) {
      requestIndex = i;
      break;
    }
  }
  if (requestIndex < 0) return { status: "none", answer: null };
  for (let i = requestIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type === "final_answer") {
      return { status: "answered", answer: String(event.content_delta ?? "") };
    }
    if (event.type === "error") return { status: "failed", answer: null };
  }
  return { status: "pending", answer: null };
}

/** Case-tolerant match of a reported path against the known changed files (suffix/prefix aware). */
function matchKnownFile(candidate: string, knownFiles: string[]): string | null {
  const normalized = candidate.replace(/\\/g, "/").replace(/^\.\//, "");
  for (const known of knownFiles) {
    const normalKnown = known.replace(/\\/g, "/");
    if (
      normalKnown === normalized ||
      normalKnown.endsWith(`/${normalized}`) ||
      normalized.endsWith(`/${normalKnown}`)
    ) {
      return known;
    }
  }
  return null;
}

// One finding per line: `path:line — note` (also tolerates -, :, ： as the separator and list
// bullets/numbering in front). The path must resolve to a known changed file — this is what keeps
// a hallucinated or prose-mentioned path from becoming a fake anchor.
const FINDING_PATTERN =
  /^[\s>*\-\d.、）)]*`?([\w./\\-]+\.[A-Za-z0-9_]+)`?[:：](\d+)`?\s*[—\-–:：]\s*(.+)$/;

export function parseReviewFindings(answer: string, knownFiles: string[]): ReviewFinding[] {
  const findings: ReviewFinding[] = [];
  const seen = new Set<string>();
  for (const rawLine of String(answer ?? "").split(/\r?\n/)) {
    const match = rawLine.match(FINDING_PATTERN);
    if (!match) continue;
    const file = matchKnownFile(match[1], knownFiles);
    if (!file) continue;
    const line = Number(match[2]);
    const note = match[3].trim();
    const key = `${file}:${line}:${note}`;
    if (seen.has(key) || !note) continue;
    seen.add(key);
    findings.push({ file, line: Number.isFinite(line) ? line : null, note });
  }
  return findings;
}

/** True when the model explicitly declared the diff clean. */
export function isCleanVerdict(answer: string | null): boolean {
  return Boolean(answer && answer.includes(NO_FINDINGS_MARKER));
}
