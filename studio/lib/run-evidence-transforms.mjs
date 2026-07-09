// Pure run-evidence transform helpers, extracted verbatim from server.mjs. These are leaf
// functions — they derive UI-facing data from already-loaded run events / payloads and call
// nothing outside this module (no fs, no server state). The heavier evidence readers that DO
// touch the filesystem or other server helpers (readRunDetail, buildWorkerTree, enrichRuntimeProgress,
// buildPromotionPreview, …) stay in server.mjs for now and import these.

export function runtimeRequestDetailValues(requests, keys) {
  const values = [];
  for (const request of requests || []) {
    const details = request?.details && typeof request.details === "object" ? request.details : {};
    for (const key of keys) {
      const raw = details[key];
      const candidates = Array.isArray(raw) ? raw : raw ? [raw] : [];
      for (const candidate of candidates) {
        const value = String(candidate).trim();
        if (value && !values.includes(value)) values.push(value);
      }
    }
  }
  return values;
}

export function scopeValueSummary(values) {
  const visible = values.slice(0, 3);
  return `${visible.join(", ")}${values.length > visible.length ? `, and ${values.length - visible.length} more` : ""}`;
}

export function latestMainTranscriptEvent(events, transcriptKind) {
  if (!Array.isArray(events)) return null;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.display_level === "inspector") continue;
    if (event.transcript_kind === transcriptKind) return event;
  }
  return null;
}

export function latestMainToolEvent(events) {
  return (
    latestMainTranscriptEvent(events, "tool_use") ||
    latestMainTranscriptEvent(events, "tool_result")
  );
}

export function latestMainFinalEvent(events) {
  return latestMainTranscriptEvent(events, "final") || latestMainTranscriptEvent(events, "stop");
}

export function flattenWorkerNodes(workerTree) {
  const result = [];
  const visit = (node, depth = 0) => {
    if (!node || typeof node !== "object") return;
    result.push({
      worker_invocation_id: node.worker_invocation_id,
      task_id: node.task_id,
      status: node.status,
      result_status: node.result_status,
      execution_profile_id: node.execution_profile_id,
      spawn_kind: node.spawn_kind,
      fake_path: node.fake_path ?? null,
      scheduling_mode: node.scheduling_mode || null,
      depth,
    });
    for (const child of Array.isArray(node.children) ? node.children : []) visit(child, depth + 1);
  };
  for (const root of Array.isArray(workerTree.roots) ? workerTree.roots : []) visit(root, 0);
  return result;
}

export function promotionPreviewHint(promotionPreview) {
  if (!promotionPreview || typeof promotionPreview !== "object") return "";
  const pending = Number(promotionPreview.pending_promotions ?? 0);
  const exportCount = Number(promotionPreview.export_count ?? 0);
  const mergeStatus = String(promotionPreview.merge_preview_status ?? "");
  if (pending > 0) {
    return `${pending} candidate change${pending === 1 ? "" : "s"} waiting for your review in Inspector.`;
  }
  if (mergeStatus === "needs_review") {
    return String(
      promotionPreview.merge_preview_summary || "Some candidate changes need review before merge.",
    );
  }
  if (exportCount > 0 && mergeStatus === "ready") {
    return `${exportCount} candidate export${exportCount === 1 ? "" : "s"} passed merge preview.`;
  }
  return "";
}

export function latestDecisions(decisions) {
  const byId = new Map();
  const anonymous = [];
  for (const decision of decisions || []) {
    const decisionId = String(decision?.decision_id || "").trim();
    if (!decisionId) {
      anonymous.push(decision);
      continue;
    }
    byId.set(decisionId, decision);
  }
  return [...anonymous, ...byId.values()];
}
