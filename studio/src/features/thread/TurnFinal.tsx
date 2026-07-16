import React, { useState } from "react";
import { Check, Copy } from "lucide-react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { MarkdownBody } from "../../components/MarkdownBody";
import { cleanReasoning } from "../../narrative";
import { turnModelMetadata } from "./turnHelpers";

const ERROR_CATEGORY_LABELS: Record<string, string> = {
  auth: "鉴权",
  rate_limit: "限流",
  timeout: "超时",
  network: "网络",
  model: "模型",
};

export function TurnFinal({
  step,
  middleSteps,
}: {
  step: NarrativeStepType;
  middleSteps: NarrativeStepType[];
}) {
  const event = step.events[0];
  // The closing answer is the MODEL's real prose only (its streamed content_delta / recap). We do NOT
  // fall back to step.summary/title — those are harness-authored status strings ("task-X completed
  // with verified evidence"), and using them here is a self-certification impersonating the model
  // (ADR-0021). When the model produced no prose, render nothing / a neutral note — never a fake pass.
  const isError = step.kind === "error" || step.status === "failed";
  const text = event?.content_delta || (isError ? event?.summary || step.summary || "" : "");
  const visibleText = humanizeRunConclusion(stripContextNoise(cleanReasoning(text)));
  const modelMeta = turnModelMetadata(middleSteps, step);
  const { lead, details } = splitLeadAndDetails(visibleText);
  // Honesty: never fabricate a "Done." success for a content-less non-error final. Show the real
  // final text when present; otherwise render nothing (or a neutral note), never a fake outcome.
  const leadText = lead || (isError ? "收尾时出了点问题。" : "");
  // Coarse error category (auth/rate_limit/timeout/network/model) badged from the real error, when
  // the runtime actually detected one — never invented (I12).
  const category = isError
    ? String((event?.data as Record<string, unknown> | undefined)?.error_category ?? "")
    : "";
  const categoryLabel = ERROR_CATEGORY_LABELS[category] ?? "";

  const [copied, setCopied] = useState(false);
  const copyText = (lead ? `${lead}${details ? `\n\n${details}` : ""}` : visibleText).trim();
  async function copyAnswer() {
    if (!copyText) return;
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className={`turnFinal ${isError ? "failed" : ""}`}>
      <div className="turnFinalHeader">
        <span className="turnFinalAvatar">A</span>
        <span className="turnFinalLabel">Asteria</span>
        {categoryLabel && <span className="turnFinalErrorTag">{categoryLabel}</span>}
        {modelMeta && <span className="turnFinalMeta">{modelMeta}</span>}
        {copyText && (
          <button
            type="button"
            className="turnFinalCopy"
            title="复制回答"
            aria-label="复制回答"
            onClick={() => void copyAnswer()}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            <span>{copied ? "已复制" : "复制"}</span>
          </button>
        )}
      </div>
      <div className="turnFinalText">
        {leadText ? (
          <MarkdownBody text={leadText} />
        ) : (
          !details && (
            <span className="turnFinalEmpty" style={{ opacity: 0.6 }}>
              (无最终结果)
            </span>
          )
        )}
        {details && (
          <details className="turnFinalDetails">
            <summary>运行详情</summary>
            <MarkdownBody text={details} />
          </details>
        )}
      </div>
    </div>
  );
}

/**
 * When the model-authored recap is empty, the runtime's fallback conclusion is a status line that
 * leaks internals — `Run run-20260705-0002 已完成，状态：completed。共 4 个执行步骤。` (run id, status
 * enum, step count). The outcome the user cares about is already carried by the file cards + the
 * verification badge, so project that template to a plain human sentence. Non-matching text (a real
 * conversational recap) passes through untouched.
 */
function humanizeRunConclusion(text: string): string {
  const match = String(text || "").match(
    /^Run\s+run-[\w-]+\s+已完成，状态：(\w+)。共\s*\d+\s*个执行步骤。?\s*$/,
  );
  if (!match) return text;
  switch (match[1].toLowerCase()) {
    case "completed":
      return "已完成本次任务。";
    case "blocked":
      return "本次运行被阻塞，需要你处理后再继续。";
    case "paused":
      return "本次运行已暂停。";
    default:
      return "本次运行已结束。";
  }
}

function stripContextNoise(text: string): string {
  const backendNoise =
    /\n(?:Context refs:|Current session:|Next actions:|Model route:|Route rationale:|Evidence refs:|Artifact refs:|Run id:|Latest run:)/i;
  return String(text || "")
    .split(backendNoise)[0]
    .replace(/\n?_Answered with model route:[\s\S]*$/i, "")
    .replace(/\n?_Local fallback answer:[\s\S]*$/i, "")
    .replace(/^Latest run:\s*`?run-[^\n]+\n?/gim, "")
    .replace(/^.*(?:Inspector|Evidence Explorer).*$/gim, "")
    .trim();
}

/**
 * Conversation-first split (ADR-0012): fold ONLY a recognizable harness-authored tail (legacy
 * report-style finals ended with 计划/验证/执行过程 sections) into the collapsed "运行详情"
 * disclosure. The model's own prose is NEVER amputated: the previous heuristic ("≥2 headings →
 * collapse everything after the first section") hid the actual answer body of any structured
 * model reply (a multi-section explanation lost all sections but the first) behind a disclosure
 * whose label lied about what it contained. Modern recaps are prompted to contain no markdown
 * sections at all (run_recap.py), so this allowlist only ever fires on legacy stored events.
 */
const HARNESS_TAIL_HEADING =
  /^#{2,6}\s*(计划|执行过程|运行过程|验证(结果)?|证据|运行详情|plan|process( summary)?|verification|evidence)\s*$/i;

function splitLeadAndDetails(text: string): { lead: string; details: string } {
  const raw = String(text || "");
  const lines = raw.split(/\r?\n/);
  const tailStart = lines.findIndex((line) => HARNESS_TAIL_HEADING.test(line.trim()));
  if (tailStart === -1) return { lead: raw.trim(), details: "" };
  return {
    lead: lines.slice(0, tailStart).join("\n").trim(),
    details: lines.slice(tailStart).join("\n").trim(),
  };
}
