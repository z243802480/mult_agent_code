import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Banner } from "./components/Shared";
import { Sidebar } from "./components/Sidebar";
import { Thread } from "./components/Thread";
import { SidePanel } from "./components/SidePanel";
import { Composer } from "./components/Composer";
import { MissionPaneHeader } from "./layout/MissionPaneHeader";
import { usePaneLayout } from "./hooks/usePaneLayout";
import { useThreadColumnWidth } from "./hooks/useThreadColumnWidth";
import { useViewMode } from "./hooks/useViewMode";
import { useDiffFocus } from "./hooks/useDiffFocus";
import { useStudioKeyboard } from "./hooks/useStudioKeyboard";
import { useStudioBootstrap } from "./session/useStudioBootstrap";
import { useSessionEvents } from "./session/useSessionEvents";
import { useRunEvidence } from "./session/useRunEvidence";
import { useSideChat } from "./hooks/useSideChat";
import { SideChatPanel } from "./features/sidechat/SideChatPanel";
import { useWorkspaceReview } from "./session/useWorkspaceReview";
import type { StudioSession } from "./types";

export function App() {
  const [panelOpen, setPanelOpen] = useState(true);
  const paneLayout = usePaneLayout();
  const missionPaneRef = useRef<HTMLElement | null>(null);
  const threadMax = useThreadColumnWidth(missionPaneRef);
  const { viewMode, cycleViewMode } = useViewMode();
  const { diffFocus, toggleDiffFocus } = useDiffFocus();
  const { sideChatOpen, setSideChatOpen, toggleSideChat, closeSideChat, composerSideAsk, toggleComposerSideAsk } = useSideChat();
  const [sideChatSending, setSideChatSending] = useState(false);

  const reviewRef = useRef<ReturnType<typeof useWorkspaceReview> | null>(null);
  const runEvidenceRef = useRef<ReturnType<typeof useRunEvidence> | null>(null);

  const bootstrap = useStudioBootstrap({
    onOverviewReady: async (overview) => {
      await runEvidenceRef.current?.openLatestRun(overview);
      await reviewRef.current?.refreshGitStatus();
    },
  });

  const sessionEvents = useSessionEvents(
    bootstrap.activeSession,
    bootstrap.sessions,
    bootstrap.setSessions,
  );

  const runEvidence = useRunEvidence(sessionEvents.events, () => {
    void reviewRef.current?.refreshGitStatus();
  });
  runEvidenceRef.current = runEvidence;

  const review = useWorkspaceReview(
    bootstrap.activeSession,
    sessionEvents.events,
    runEvidence.selectedRunId,
    runEvidence.setRunDetail,
  );
  reviewRef.current = review;

  const {
    panelWidth,
    setPanelWidth,
    sidebarCollapsed,
    effectiveSidebarWidth,
    toggleSidebarCollapsed,
    startSidebarDrag,
    startPanelDrag,
    resetSidebar,
    resetPanel,
  } = paneLayout;

  useEffect(() => {
    if (!diffFocus) return;
    setPanelOpen(true);
    if (panelWidth < 360) {
      setPanelWidth(400);
    }
  }, [diffFocus, panelWidth, setPanelWidth]);

  const selectSession = useCallback((session: StudioSession) => {
    bootstrap.setActiveSession(session);
    runEvidence.clearSelection();
    sessionEvents.clearEvents();
    review.applySessionUiState(session);
  }, [bootstrap, runEvidence, sessionEvents, review]);

  useStudioKeyboard({
    sessions: bootstrap.sessions,
    activeSessionId: bootstrap.activeSession?.session_id,
    onTogglePanel: () => setPanelOpen((open) => !open),
    onToggleSidebar: toggleSidebarCollapsed,
    onToggleDiffFocus: toggleDiffFocus,
    onToggleSideChat: toggleSideChat,
    onSelectSession: selectSession,
  });

  const shellClassName = useMemo(() => [
    "appShell",
    panelOpen ? "panelOpen" : "panelCollapsed",
    sidebarCollapsed ? "sidebarCollapsed" : "",
    diffFocus ? "diffFocus" : "",
    `view-${viewMode}`,
  ].filter(Boolean).join(" "), [panelOpen, sidebarCollapsed, diffFocus, viewMode]);

  const sendSideAsk = useCallback(async (message: string) => {
    setSideChatOpen(true);
    setSideChatSending(true);
    try {
      await sessionEvents.sendSideAsk(message);
    } finally {
      setSideChatSending(false);
    }
  }, [sessionEvents, setSideChatOpen]);

  const resolveDecision = useCallback((
    runId: string,
    decisionId: string,
    optionId: string,
  ) => sessionEvents.resolveDecision(runId, decisionId, optionId, runEvidence.setRunDetail), [sessionEvents, runEvidence.setRunDetail]);

  const onTurnRewind = useCallback(async (_turnIndex: number, action: string) => {
    await sessionEvents.runRuntimeAction(action);
  }, [sessionEvents]);

  const openReviewFile = useCallback(async (pathValue: string) => {
    setPanelOpen(true);
    await review.refreshGitStatus();
    await review.openFileChange(pathValue);
  }, [review]);

  const openTurnReview = useCallback((turnIndex: number) => {
    setPanelOpen(true);
    void review.refreshGitStatus();
    review.selectTurnDiff(turnIndex);
  }, [review]);

  const openCurrentReview = useCallback(async () => {
    setPanelOpen(true);
    const status = await review.refreshGitStatus();
    const firstPath = review.gitSelectedPath ?? status.changes?.[0]?.path;
    if (firstPath) {
      await review.openFileChange(firstPath);
    }
  }, [review]);

  const runRuntimeAction = useCallback(async (action: string) => {
    if (/^(review|accept)\b/i.test(action.trim())) {
      await openCurrentReview();
    }
    await sessionEvents.runRuntimeAction(action);
  }, [openCurrentReview, sessionEvents]);

  return (
    <div
      className={shellClassName}
      style={{
        ["--sidebar-width" as string]: `${effectiveSidebarWidth}px`,
        ["--panel-width" as string]: `${panelWidth}px`,
        ["--thread-max" as string]: `${threadMax}px`,
      }}
    >
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebarCollapsed}
        sessions={bootstrap.sessions}
        active={bootstrap.activeSession}
        overview={bootstrap.overview}
        settings={bootstrap.settings}
        isRunning={sessionEvents.isRunning}
        onSelect={selectSession}
        onNew={() => void bootstrap.newSession(() => {
          runEvidence.clearSelection();
          sessionEvents.clearEvents();
        })}
        onDelete={(session) => void bootstrap.deleteSession(session, () => {
          runEvidence.clearSelection();
          sessionEvents.clearEvents();
        })}
        onRename={async (session, title) => {
          const result = await api.updateSession(session.session_id, { title });
          bootstrap.setSessions(bootstrap.sessions.map((item) => (
            item.session_id === session.session_id ? result.session : item
          )));
          if (bootstrap.activeSession?.session_id === session.session_id) {
            bootstrap.setActiveSession(result.session);
          }
        }}
        onWorkspaceChanged={() => void bootstrap.bootstrap()}
        workspaceOpen={bootstrap.workspaceOpen}
        onWorkspaceOpenChange={bootstrap.setWorkspaceOpen}
        viewMode={viewMode}
      />
      {!sidebarCollapsed && (
        <div
          className="paneSplitter sidebarSplitter"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          title="Drag to resize · double-click to reset"
          onMouseDown={startSidebarDrag}
          onDoubleClick={resetSidebar}
        />
      )}
      <main className="missionPane" ref={missionPaneRef}>
        <MissionPaneHeader
          title={bootstrap.activeSession?.title ?? "New task"}
          settings={bootstrap.settings}
          runDetail={runEvidence.runDetail}
          isRunning={sessionEvents.isRunning}
          viewMode={viewMode}
          panelOpen={panelOpen}
          diffFocus={diffFocus}
          loading={bootstrap.loading}
          onOpenWorkspace={() => bootstrap.setWorkspaceOpen(true)}
          onCycleViewMode={cycleViewMode}
          onTogglePanel={() => setPanelOpen((open) => !open)}
          onToggleDiffFocus={toggleDiffFocus}
          onToggleSideChat={toggleSideChat}
          sideChatOpen={sideChatOpen || composerSideAsk}
          onRefresh={() => void bootstrap.bootstrap()}
        />
        {bootstrap.error && <Banner tone="bad" text={bootstrap.error} />}
        <Thread
          events={sessionEvents.events}
          selected={runEvidence.selectedEvent}
          isRunning={sessionEvents.isRunning}
          onSelect={runEvidence.selectEvent}
          onPrompt={bootstrap.pushPrompt}
          onPermit={sessionEvents.permitJob}
          onRuntimeAction={runRuntimeAction}
          onOpenReview={openCurrentReview}
          onResolveDecision={resolveDecision}
          pendingTurn={sessionEvents.pendingTurn}
          overview={bootstrap.overview}
          runDetail={runEvidence.runDetail}
          workspaceChangeCount={review.gitStatus?.change_count ?? review.gitStatus?.changes?.length ?? 0}
          onFileChangeClick={(pathValue) => void openReviewFile(pathValue)}
          onTurnDiffSelect={openTurnReview}
          turnDiffLabel={(turnIndex) =>
            review.turnDiffScopes.find((scope) => scope.turnIndex === turnIndex)?.label ?? `T${turnIndex}`
          }
          onAggregateDiffClick={openTurnReview}
          viewMode={viewMode}
          onTurnRewind={onTurnRewind}
        />
        <Composer
          onSend={sessionEvents.sendGoal}
          onSideAsk={sendSideAsk}
          sideAsk={composerSideAsk}
          onSideAskToggle={toggleComposerSideAsk}
          promptSignal={bootstrap.promptSignal}
          viewMode={viewMode}
        />
      </main>
      {panelOpen && (
        <>
          <div
            className="paneSplitter panelSplitter"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize side panel"
            title="Drag to resize · double-click to reset"
            onMouseDown={startPanelDrag}
            onDoubleClick={resetPanel}
          />
          <SidePanel
            event={runEvidence.selectedEvent}
            files={bootstrap.files}
            preview={review.preview}
            settings={bootstrap.settings}
            overview={bootstrap.overview}
            selectedRunId={runEvidence.selectedRunId}
            runDetail={runEvidence.runDetail}
            gitStatus={review.gitStatus}
            gitLoading={review.gitLoading}
            gitSelectedPath={review.gitSelectedPath}
            diffScopes={review.turnDiffScopes}
            diffScopeId={review.diffScopeId}
            onSelectDiffScope={review.setDiffScope}
            diffStage={review.diffStage}
            onSelectDiffStage={review.setDiffStageAndReload}
            diffLayout={review.diffLayout}
            onSelectDiffLayout={review.setDiffLayoutMode}
            gitDiffPayload={review.gitDiffPayload}
            gitActionLoading={review.gitActionLoading}
            onStageFile={() => void review.stageSelectedFile()}
            onDiscardFile={() => void review.discardSelectedFile()}
            contextSectionId={review.contextSectionId}
            onSelectContextSection={review.setContextSectionId}
            onCompactContext={() => void review.compactContext()}
            compactLoading={review.compactLoading}
            isRunning={sessionEvents.isRunning}
            onRefreshGit={() => void review.refreshGitStatus()}
            onSelectGitChange={(pathValue) => void review.openGitDiff(pathValue)}
            onOpenFile={review.openFile}
            onOpenRun={runEvidence.openRun}
            onSelectRunEvent={runEvidence.selectRunEvidenceEvent}
            viewMode={viewMode}
          />
        </>
      )}
      <SideChatPanel
        open={sideChatOpen}
        events={sessionEvents.events}
        sending={sideChatSending}
        onClose={closeSideChat}
        onSend={sendSideAsk}
      />
    </div>
  );
}
