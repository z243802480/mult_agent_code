import React from "react";
import { ArrowUpRight, FileText } from "lucide-react";
import type {
  AnyRecord,
  OverviewPayload,
  RunDetailPayload,
  SettingsPayload,
  StudioEvent,
  WorkspaceFile,
} from "../../types";
import { formatMs, percent } from "../../components/Shared";
import type { StudioViewMode } from "../../hooks/useViewMode";
import { AiDebugAgentCard } from "./AiDebugAgentCard";
import { BackgroundRunPanel, EvidenceExplorer, LongHorizonPanel } from "./EvidenceExplorer";
import { buildInspectorSections, InspectorTabs } from "./SelectedStepPanel";

export type InspectorAdvancedProps = {
  event: StudioEvent | null;
  files: WorkspaceFile[];
  settings: SettingsPayload | null;
  overview: OverviewPayload | null;
  selectedRunId: string | null;
  runDetail: RunDetailPayload | null;
  contextSectionId: string | null;
  viewMode: StudioViewMode;
  onOpenFile: (path: string) => Promise<void>;
  onOpenRun: (runId: string) => Promise<void>;
  onSelectRunEvent: (event: StudioEvent) => void;
};

export function InspectorAdvanced({
  event,
  files,
  settings,
  overview,
  selectedRunId,
  runDetail,
  contextSectionId,
  viewMode,
  onOpenFile,
  onOpenRun,
  onSelectRunEvent,
}: InspectorAdvancedProps) {
  const eventFiles = files.slice(0, 12);
  const routes = (overview?.modelRoutes?.slice(0, 5) ?? []) as AnyRecord[];
  const inspectorSections = React.useMemo(() => buildInspectorSections(event, onOpenFile), [event, onOpenFile]);
  const showRunOverviewFirst = !event && Boolean(runDetail?.ok);
  const advancedOpen = viewMode === "verbose";

  return (
    <details className="inspectorAdvanced" open={advancedOpen}>
      <summary>Evidence &amp; debug</summary>
      <div className="inspectorAdvancedBody">
        <AiDebugAgentCard runDetail={runDetail} selectedRunId={selectedRunId} />
        <BackgroundRunPanel overview={overview} />
        <LongHorizonPanel overview={overview} />
        {showRunOverviewFirst && (
          <EvidenceExplorer
            runs={(overview?.runs ?? []) as AnyRecord[]}
            overview={overview}
            selectedRunId={selectedRunId}
            runDetail={runDetail}
            onOpenRun={onOpenRun}
            onOpenFile={onOpenFile}
            onSelectRunEvent={onSelectRunEvent}
          />
        )}
        <section>
          <h2>Selected step</h2>
          {!event && <p className="muted">Select a process step in the thread to inspect raw diagnostics.</p>}
          {event && (
            <div className="detail">
              <InspectorTabs sections={inspectorSections} />
            </div>
          )}
        </section>
        <section>
          <h2>Model routes</h2>
          <div className="routeList">
            {routes.length === 0 && <p className="muted">No route telemetry yet.</p>}
            {routes.map((route) => (
              <div className="routeItem" key={String(route.key ?? "")}>
                <strong>{String(route.provider ?? "")}/{String(route.model ?? "")}</strong>
                <small>{String(route.purpose ?? "")} · {String(route.tier ?? "")} · {percent(route.successRate)} success</small>
                <small>{String(route.total ?? 0)} calls · p95 {formatMs(route.durationP95)}</small>
              </div>
            ))}
          </div>
        </section>
        {!showRunOverviewFirst && (
          <EvidenceExplorer
            runs={(overview?.runs ?? []) as AnyRecord[]}
            overview={overview}
            selectedRunId={selectedRunId}
            runDetail={runDetail}
            onOpenRun={onOpenRun}
            onOpenFile={onOpenFile}
            onSelectRunEvent={onSelectRunEvent}
          />
        )}
        {eventFiles.length > 0 && (
          <section>
            <h2>Workspace files</h2>
            <div className="fileList">
              {eventFiles.map((file) => (
                <button key={file.path} type="button" onClick={() => void onOpenFile(file.path)}>
                  <FileText size={14} />
                  <span>{file.path}</span>
                  <ArrowUpRight size={13} />
                </button>
              ))}
            </div>
          </section>
        )}
        {contextSectionId && runDetail && (
          <div className="contextSectionDetail">
            <strong>Context section: {contextSectionId}</strong>
            <p className="muted">See Evidence Explorer above for raw refs tied to this run.</p>
          </div>
        )}
        <section>
          <h2>Runtime</h2>
          <p className="muted">Mode: {settings?.workMode ?? "unknown"}</p>
          <p className="muted">Permission: {settings?.permissionMode ?? "unknown"}</p>
          <p className="muted">Shell: {settings?.shell ?? "unknown"}</p>
        </section>
      </div>
    </details>
  );
}
