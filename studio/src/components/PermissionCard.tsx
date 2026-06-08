import React, { useState } from "react";
import { CheckCircle2, FilePenLine, FolderLock, Globe2, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import type { PermissionPreview, StudioEvent } from "../types";

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
        <span>{"\u5df2\u786e\u8ba4\uff0c\u6b63\u5728\u5f00\u59cb\u5904\u7406..."}</span>
      </div>
    );
  }
  if (resolved === "denied") {
    return (
      <div className="permissionCard resolved deny">
        <XCircle size={15} />
        <span>{"\u5df2\u53d6\u6d88\uff0c\u672c\u6b21\u4e0d\u4f1a\u7ee7\u7eed\u6267\u884c\u3002"}</span>
      </div>
    );
  }

  const preview = permissionPreview(event);

  return (
    <div className="permissionCard">
      <div className="permissionHeader">
        <ShieldAlert size={16} />
        <strong>{event.title || "\u9700\u8981\u4f60\u786e\u8ba4"}</strong>
      </div>
      <p className="permissionSummary">{event.summary}</p>
      {event.content_delta && !preview && <p className="permissionDetail">{event.content_delta}</p>}
      {preview && (
        <div className="permissionPreview" aria-label="Permission impact">
          {preview.action && <PermissionFact label="Action" value={preview.action} icon={<ShieldAlert size={13} />} />}
          {preview.impact && <PermissionFact label="Impact" value={preview.impact} icon={<FilePenLine size={13} />} />}
          {preview.scope && <PermissionFact label="Scope" value={preview.scope} icon={<FolderLock size={13} />} />}
          {preview.network && <PermissionFact label="Network" value={preview.network} icon={<Globe2 size={13} />} />}
          {(preview.risk || preview.reversible) && (
            <PermissionFact
              label={`Risk${preview.risk ? ` · ${preview.risk}` : ""}`}
              value={preview.reversible || "Review the impact before continuing."}
              icon={<RotateCcw size={13} />}
            />
          )}
        </div>
      )}
      <div className="permissionActions">
        <button className="permissionAllow" disabled={busy} onClick={() => void handle("allow")}>
          <CheckCircle2 size={14} /> {"\u786e\u8ba4\u7ee7\u7eed"}
        </button>
        <button className="permissionDeny" disabled={busy} onClick={() => void handle("deny")}>
          <XCircle size={14} /> {"\u53d6\u6d88"}
        </button>
      </div>
    </div>
  );
}

function permissionPreview(event: StudioEvent): PermissionPreview | null {
  const value = event.data?.permission_preview;
  return value && typeof value === "object" ? value as PermissionPreview : null;
}

function PermissionFact({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="permissionFact">
      <span>{icon}</span>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}
