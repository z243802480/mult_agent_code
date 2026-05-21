import React, { useState } from "react";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import type { StudioEvent } from "../types";

export function PermissionCard({
  event,
  onAllow,
  onDeny,
}: {
  event: StudioEvent;
  onAllow: () => Promise<void>;
  onDeny: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [resolved, setResolved] = useState<"allowed" | "denied" | null>(null);

  async function handle(action: "allow" | "deny") {
    setBusy(true);
    try {
      if (action === "allow") { await onAllow(); setResolved("allowed"); }
      else { await onDeny(); setResolved("denied"); }
    } finally {
      setBusy(false);
    }
  }

  if (resolved === "allowed") {
    return (
      <div className="permissionCard resolved allow">
        <CheckCircle2 size={15} />
        <span>已授权，正在启动...</span>
      </div>
    );
  }
  if (resolved === "denied") {
    return (
      <div className="permissionCard resolved deny">
        <XCircle size={15} />
        <span>已取消</span>
      </div>
    );
  }

  return (
    <div className="permissionCard">
      <div className="permissionHeader">
        <ShieldAlert size={16} />
        <strong>{event.title}</strong>
      </div>
      <p className="permissionSummary">{event.summary}</p>
      {event.content_delta && <p className="permissionDetail">{event.content_delta}</p>}
      {event.command && event.command.length > 0 && (
        <code className="permissionCommand">{event.command.join(" ")}</code>
      )}
      <div className="permissionActions">
        <button className="permissionAllow" disabled={busy} onClick={() => void handle("allow")}>
          <CheckCircle2 size={14} /> 允许执行
        </button>
        <button className="permissionDeny" disabled={busy} onClick={() => void handle("deny")}>
          <XCircle size={14} /> 取消
        </button>
      </div>
    </div>
  );
}
