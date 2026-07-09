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
  embedded?: boolean;
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
  embedded = false,
  onOpenFile,
  onOpenRun,
  onSelectRunEvent,
}: InspectorAdvancedProps) {
  const eventFiles = files.slice(0, 12);
  const routes = (overview?.modelRoutes?.slice(0, 5) ?? []) as AnyRecord[];
  const inspectorSections = React.useMemo(
    () => buildInspectorSections(event, onOpenFile),
    [event, onOpenFile],
  );
  const showRunOverviewFirst = !event && Boolean(runDetail?.ok);
  const advancedOpen = viewMode === "verbose";

  const body = (
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
        <h2>所选步骤</h2>
        {!event && <p className="muted">在对话中选择一个流程步骤,查看其原始诊断信息。</p>}
        {event && (
          <div className="detail">
            <InspectorTabs sections={inspectorSections} />
          </div>
        )}
      </section>
      <section>
        <h2>模型路由</h2>
        <div className="routeList">
          {routes.length === 0 && <p className="muted">暂无路由遥测数据。</p>}
          {routes.map((route) => (
            <div className="routeItem" key={String(route.key ?? "")}>
              <strong>
                {String(route.provider ?? "")}/{String(route.model ?? "")}
              </strong>
              <small>
                {String(route.purpose ?? "")} · {String(route.tier ?? "")} ·{" "}
                {percent(route.successRate)} 成功率
              </small>
              <small>
                {String(route.total ?? 0)} 次调用 · p95 {formatMs(route.durationP95)}
              </small>
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
          <h2>工作区文件</h2>
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
          <strong>上下文分区: {contextSectionId}</strong>
          <p className="muted">查看上方的证据浏览器,了解与本次运行相关的原始引用。</p>
        </div>
      )}
      <section>
        <h2>运行时</h2>
        <p className="muted">模式: {settings?.workMode ?? "unknown"}</p>
        <p className="muted">权限: {settings?.permissionMode ?? "unknown"}</p>
        <p className="muted">Shell: {settings?.shell ?? "unknown"}</p>
      </section>
    </div>
  );

  // In the tabbed Inspector (INS-1) the Evidence tab is itself the disclosure, so render the body
  // directly. Legacy stacked layout keeps the <details> wrapper.
  if (embedded) return body;
  return (
    <details className="inspectorAdvanced" open={advancedOpen}>
      <summary>证据与调试</summary>
      {body}
    </details>
  );
}
