import React, { useEffect, useMemo, useRef, useState } from "react";
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
import type { DiffLayout, DiffStage } from "../../components/DiffPreview";
import { ContextPanel } from "../../components/ContextPanel";
import type { StudioViewMode } from "../../hooks/useViewMode";
import type { TurnDiffScope } from "../../turnDiff";
import { extractFileChangesFromEvents } from "../../fileChanges";
import { isCleanVerdict, latestAiReview, parseReviewFindings } from "../../session/aiReview";
import { DiffReviewPane } from "./DiffReviewPane";
import { InspectorAdvanced } from "./InspectorAdvanced";
import { MemoryPanel } from "./MemoryPanel";
import { PreviewPane } from "./PreviewPane";
import { SubagentPanel } from "./SubagentPanel";

// INS-1/INS-3: the Inspector is a focused tabbed workspace panel (was a ~2000px vertical evidence
// stack). Preview renders the live built result (like Claude Code / Cursor); Changes = diffs;
// Context = context window; Evidence = raw diagnostics for power users.
const INSPECTOR_TABS = [
  { id: "preview", label: "预览" },
  { id: "changes", label: "改动" },
  { id: "context", label: "上下文" },
  { id: "memory", label: "记忆" },
  { id: "agents", label: "子 agent" },
  { id: "evidence", label: "证据" },
] as const;
type InspectorTabId = (typeof INSPECTOR_TABS)[number]["id"];
const TAB_STORAGE_KEY = "asteria.studio.inspectorTab";

function loadInspectorTab(): InspectorTabId {
  try {
    const raw = localStorage.getItem(TAB_STORAGE_KEY);
    if (
      raw === "preview" ||
      raw === "changes" ||
      raw === "context" ||
      raw === "memory" ||
      raw === "agents" ||
      raw === "evidence"
    )
      return raw;
  } catch {
    // ignore
  }
  return "preview";
}

export function Inspector({
  event,
  events,
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
  tabSignal,
  onAiReview,
  aiReviewBusy = false,
}: {
  event: StudioEvent | null;
  events: StudioEvent[];
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
  /** External focus request (e.g. the header's context ring) — same pattern as expandSignal. */
  tabSignal?: { id: number; tab: InspectorTabId } | null;
  /** G5 AI 自审: kick off a model review of the current workspace diff (wired in the app shell). */
  onAiReview?: () => void;
  /** True while a run is in flight (review must wait) or the review request is being assembled. */
  aiReviewBusy?: boolean;
}) {
  const [tab, setTab] = useState<InspectorTabId>(loadInspectorTab);

  // Preview is scoped to files THIS session actually touched — the workspace is shared across
  // sessions, and offering another session's artifacts here (a snake game next to an algorithm
  // chat) reads as showing an unrelated project. Same event walk the thread's file cards use.
  const sessionFilePaths = useMemo(() => {
    const source = events.length
      ? events
      : ((runDetail?.events ?? runDetail?.user_progress ?? []) as StudioEvent[]);
    return extractFileChangesFromEvents(source).map((change) => change.path);
  }, [events, runDetail]);
  // G5 AI 自审: the latest review round lives in the transcript (sentinel-prefixed user message →
  // its final answer). Findings are parsed here and hung on the diff view's file anchors.
  const aiReview = useMemo(() => latestAiReview(events), [events]);
  const aiFindings = useMemo(() => {
    if (aiReview.status !== "answered" || !aiReview.answer) return [];
    const knownFiles = (gitStatus?.changes ?? []).map((change) => change.path);
    return parseReviewFindings(aiReview.answer, knownFiles);
  }, [aiReview, gitStatus]);
  const aiReviewSummary = useMemo(() => {
    if (aiReview.status === "none") return null;
    if (aiReview.status === "pending")
      return { tone: "muted" as const, text: "AI 自审进行中——结论会回到这里和主对话。" };
    if (aiReview.status === "failed")
      return { tone: "bad" as const, text: "AI 自审未完成——主对话里有失败原因。" };
    if (isCleanVerdict(aiReview.answer))
      return { tone: "ok" as const, text: "AI 自审：未发现高信号问题。" };
    if (aiFindings.length)
      return {
        tone: "warn" as const,
        text: `AI 自审：${aiFindings.length} 条发现，挂在对应文件上。`,
      };
    return { tone: "muted" as const, text: "AI 自审已回复——结论在主对话里（未解析出文件锚点）。" };
  }, [aiReview, aiFindings]);

  const selectTab = (next: InspectorTabId) => {
    setTab(next);
    try {
      localStorage.setItem(TAB_STORAGE_KEY, next);
    } catch {
      // ignore
    }
  };

  // External tab focus (header context ring → Context tab): transient, not saved as default.
  useEffect(() => {
    if (tabSignal) setTab(tabSignal.tab);
  }, [tabSignal?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selecting a process step in the thread focuses the Evidence tab (where its detail lives) — a
  // transient focus that does not overwrite the saved default.
  const prevEventId = useRef<string | null>(null);
  useEffect(() => {
    const id = event?.event_id ?? null;
    if (id && id !== prevEventId.current) setTab("evidence");
    prevEventId.current = id;
  }, [event?.event_id]);

  return (
    <aside className={`inspector view-${viewMode}`}>
      <div className="inspectorTabBar" role="tablist" aria-label="检查器视图">
        {INSPECTOR_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "inspectorTab active" : "inspectorTab"}
            onClick={() => selectTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="inspectorTabPanel">
        {tab === "preview" && <PreviewPane files={files} sessionPaths={sessionFilePaths} />}
        {tab === "changes" && (
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
              onAiReview={onAiReview}
              aiReviewBusy={aiReviewBusy}
              aiReviewPending={aiReview.status === "pending"}
              aiReviewSummary={aiReviewSummary}
              aiFindings={aiFindings}
            />
          </div>
        )}
        {tab === "memory" && <MemoryPanel />}
        {tab === "agents" && (
          <SubagentPanel
            events={
              events.length
                ? events
                : ((runDetail?.events ?? runDetail?.user_progress ?? []) as StudioEvent[])
            }
          />
        )}
        {tab === "context" && (
          <ContextPanel
            runDetail={runDetail}
            isRunning={isRunning}
            selectedSectionId={contextSectionId}
            onSelectSection={onSelectContextSection}
            onCompact={onCompactContext}
            compacting={compactLoading}
          />
        )}
        {tab === "evidence" && (
          <InspectorAdvanced
            event={event}
            files={files}
            settings={settings}
            overview={overview}
            selectedRunId={selectedRunId}
            runDetail={runDetail}
            contextSectionId={contextSectionId}
            viewMode={viewMode}
            embedded
            onOpenFile={onOpenFile}
            onOpenRun={onOpenRun}
            onSelectRunEvent={onSelectRunEvent}
          />
        )}
      </div>
    </aside>
  );
}
