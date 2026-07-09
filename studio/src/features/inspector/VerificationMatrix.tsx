import React from "react";
import { CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import type { AnyRecord } from "../../types";
import { firstText } from "../../narrative";

type Outcome = "pass" | "fail" | "unknown";

function classifyOutcome(raw: string): Outcome {
  const value = raw.trim().toLowerCase();
  if (!value) return "unknown";
  if (/pass|success|ok|green|completed/.test(value)) return "pass";
  if (/fail|error|blocked|red/.test(value)) return "fail";
  return "unknown";
}

function OutcomeIcon({ outcome }: { outcome: Outcome }) {
  if (outcome === "pass")
    return <CheckCircle2 size={14} className="vmIcon pass" aria-label="通过" />;
  if (outcome === "fail") return <XCircle size={14} className="vmIcon fail" aria-label="失败" />;
  return <MinusCircle size={14} className="vmIcon unknown" aria-label="未记录" />;
}

/**
 * Structured verification matrix (slice #7): replaces the flat `<pre>`/single-line dump of
 * validation results with a scannable pass/fail table. Each row stays clickable so the raw
 * record still opens in the Inspector detail pane (no evidence is hidden — only re-shaped).
 */
export function VerificationMatrix({
  validations,
  selectedKey,
  onSelect,
}: {
  validations: AnyRecord[];
  selectedKey?: string;
  onSelect?: (item: AnyRecord, label: string) => void;
}) {
  if (!validations.length) {
    return (
      <div className="evidenceBlock verificationMatrix">
        <small>验证</small>
        <p className="muted">暂无验证或校验记录。</p>
      </div>
    );
  }

  const rows = validations.map((item) => {
    const name = firstText(
      String(item.name ?? ""),
      String(item.command ?? ""),
      String(item.id ?? ""),
      "校验项",
    );
    const statusText = firstText(String(item.status ?? ""), String(item.outcome ?? ""), "unknown");
    const outcome = classifyOutcome(statusText);
    const detail = firstText(
      String(item.summary ?? ""),
      String(item.reason ?? ""),
      String(item.message ?? ""),
      "",
    );
    return { item, name, statusText, outcome, detail };
  });

  const passed = rows.filter((row) => row.outcome === "pass").length;
  const failed = rows.filter((row) => row.outcome === "fail").length;

  return (
    <div className="evidenceBlock verificationMatrix">
      <div className="vmHead">
        <small>验证</small>
        <span className="vmTally">
          <span className="pass">{passed} 通过</span>
          {failed > 0 && <span className="fail">{failed} 失败</span>}
          <span className="muted">/ {rows.length}</span>
        </span>
      </div>
      <div className="vmTable" role="table">
        {rows.map((row, index) => {
          const label = `${row.name} ${row.statusText}`.trim();
          const key = `validation:${label}`;
          const active = selectedKey === key;
          return (
            <button
              type="button"
              key={`${row.name}-${index}`}
              className={`vmRow ${row.outcome} ${active ? "active" : ""}`}
              onClick={onSelect ? () => onSelect(row.item, label) : undefined}
              role="row"
            >
              <OutcomeIcon outcome={row.outcome} />
              <span className="vmName" role="cell">
                {row.name}
              </span>
              <span className={`vmStatus ${row.outcome}`} role="cell">
                {row.statusText}
              </span>
              {row.detail && (
                <span className="vmDetail" role="cell">
                  {row.detail}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Loop-quality SLO as a scannable badge row (slice #7) — replaces the multi-line `<pre>` dump.
 * loop_quality_guard is observe_then_warn (ADR-0010), not a hard stop; older runs that predate it
 * render an honest "not recorded" state.
 */
export function LoopQualityMatrix({ loopQuality }: { loopQuality: AnyRecord }) {
  const has = Object.keys(loopQuality).length > 0;
  if (!has) {
    return (
      <div className="loopQualityMatrix">
        <small>循环质量(SLO · observe_then_warn)</small>
        <p className="muted">未记录(该运行早于 loop_quality_guard)</p>
      </div>
    );
  }
  const warn = Boolean(loopQuality.warn);
  const severity = firstText(String(loopQuality.severity ?? ""), warn ? "warn" : "ok");
  const hardBlock = Boolean(loopQuality.hard_block);
  const identical = `${String(loopQuality.repeated_identical_observations ?? 0)}/${String(loopQuality.repeated_identical_window ?? "n/a")}`;
  const failedVerify = `${String(loopQuality.repeated_failed_verifications ?? 0)}/${String(loopQuality.repeated_failed_window ?? "n/a")}`;
  const reason = String(loopQuality.reason ?? "none");

  return (
    <div className="loopQualityMatrix">
      <small>循环质量(SLO · observe_then_warn)</small>
      <div className="lqBadges">
        <span className="lqBadge">
          模式 <strong>{String(loopQuality.mode ?? "n/a")}</strong>
        </span>
        <span className={`lqBadge ${warn ? "warn" : "ok"}`}>
          健康 <strong>{warn ? `warn (${severity})` : "ok"}</strong>
        </span>
        <span className="lqBadge">
          重复观测 <strong>{identical}</strong>
        </span>
        <span className="lqBadge">
          重复失败验证 <strong>{failedVerify}</strong>
        </span>
        {hardBlock && <span className="lqBadge bad">硬阻断</span>}
      </div>
      {reason && reason !== "none" && <p className="lqReason">{reason}</p>}
    </div>
  );
}
