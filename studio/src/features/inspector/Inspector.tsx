import React from "react";
import type {
  FilePreview,
  GitDiffPayload,
  GitStatusPayload,
  OverviewPayload,
  RunDetailPayload,
  SettingsPayload,
  StudioEvent,
  WorkspaceFile,
} from "../../types";
import { Status } from "../../components/Shared";
import type { DiffLayout, DiffStage } from "../../components/DiffPreview";
import { ContextPanel } from "../../components/ContextPanel";
import type { StudioViewMode } from "../../hooks/useViewMode";
import type { TurnDiffScope } from "../../turnDiff";
import { DiffReviewPane } from "./DiffReviewPane";
import { InspectorAdvanced } from "./InspectorAdvanced";

export function Inspector({
  event,
  files,
  preview,
  settings,
  overview,
  selectedRunId,
  runDetail,
  gitStatus,
  gitLoading,
  gitSelectedPath,
  diffScopes,
  diffScopeId,
  onSelectDiffScope,
  diffStage,
  onSelectDiffStage,
  diffLayout,
  onSelectDiffLayout,
  gitDiffPayload,
  gitActionLoading,
  onStageFile,
  onDiscardFile,
  contextSectionId,
  onSelectContextSection,
  onCompactContext,
  compactLoading,
  isRunning,
  onRefreshGit,
  onSelectGitChange,
  onOpenFile,
  onOpenRun,
  onSelectRunEvent,
  viewMode,
}: {
  event: StudioEvent | null;
  files: WorkspaceFile[];
  preview: FilePreview | null;
  settings: SettingsPayload | null;
  overview: OverviewPayload | null;
  selectedRunId: string | null;
  runDetail: RunDetailPayload | null;
  gitStatus: GitStatusPayload | null;
  gitLoading: boolean;
  gitSelectedPath: string | null;
  diffScopes: TurnDiffScope[];
  diffScopeId: string;
  onSelectDiffScope: (scopeId: string) => void;
  diffStage: DiffStage;
  onSelectDiffStage: (stage: DiffStage) => void;
  diffLayout: DiffLayout;
  onSelectDiffLayout: (layout: DiffLayout) => void;
  gitDiffPayload: GitDiffPayload | null;
  gitActionLoading: boolean;
  onStageFile: () => void;
  onDiscardFile: () => void;
  contextSectionId: string | null;
  onSelectContextSection: (sectionId: string) => void;
  onCompactContext: () => void;
  compactLoading: boolean;
  isRunning: boolean;
  onRefreshGit: () => void;
  onSelectGitChange: (path: string) => void;
  onOpenFile: (path: string) => Promise<void>;
  onOpenRun: (runId: string) => Promise<void>;
  onSelectRunEvent: (event: StudioEvent) => void;
  viewMode: StudioViewMode;
}) {
  const showEventPeek = viewMode !== "focus" && Boolean(event);

  return (
    <aside className={`inspector view-${viewMode}`}>
      <div className="inspectorPrimary">
        <DiffReviewPane
          gitStatus={gitStatus}
          gitLoading={gitLoading}
          gitSelectedPath={gitSelectedPath}
          diffScopes={diffScopes}
          diffScopeId={diffScopeId}
          onSelectDiffScope={onSelectDiffScope}
          onRefreshGit={onRefreshGit}
          onSelectGitChange={onSelectGitChange}
          preview={preview}
          diffStage={diffStage}
          diffLayout={diffLayout}
          gitDiffPayload={gitDiffPayload}
          gitActionLoading={gitActionLoading}
          onSelectDiffStage={onSelectDiffStage}
          onSelectDiffLayout={onSelectDiffLayout}
          onStageFile={onStageFile}
          onDiscardFile={onDiscardFile}
        />
      </div>
      <ContextPanel
        runDetail={runDetail}
        isRunning={isRunning}
        selectedSectionId={contextSectionId}
        onSelectSection={onSelectContextSection}
        onCompact={onCompactContext}
        compacting={compactLoading}
      />
      {showEventPeek && event && (
        <section className="inspectorEventPeek">
          <div className="detailTitle">
            <strong>{event.title}</strong>
            <Status status={event.status} />
          </div>
          {event.summary && <p className="eventPeekSummary">{event.summary}</p>}
        </section>
      )}
      <InspectorAdvanced
        event={event}
        files={files}
        settings={settings}
        overview={overview}
        selectedRunId={selectedRunId}
        runDetail={runDetail}
        contextSectionId={contextSectionId}
        viewMode={viewMode}
        onOpenFile={onOpenFile}
        onOpenRun={onOpenRun}
        onSelectRunEvent={onSelectRunEvent}
      />
    </aside>
  );
}
