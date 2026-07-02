import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Banner } from "./components/Shared";
import { Sidebar } from "./components/Sidebar";
import { Thread } from "./components/Thread";
import { SidePanel } from "./components/SidePanel";
import { Composer } from "./components/Composer";
import { MissionPaneHeader } from "./layout/MissionPaneHeader";
import { usePaneLayout } from "./hooks/usePaneLayout";
import { useViewMode } from "./hooks/useViewMode";
import { useDiffFocus } from "./hooks/useDiffFocus";
import { useStudioKeyboard } from "./hooks/useStudioKeyboard";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { useStudioBootstrap } from "./session/useStudioBootstrap";
import { useSessionEvents } from "./session/useSessionEvents";
import { useRunEvidence } from "./session/useRunEvidence";
import { useSideChat } from "./hooks/useSideChat";
import { SideChatPanel } from "./features/sidechat/SideChatPanel";
import { useWorkspaceReview } from "./session/useWorkspaceReview";
import { ToastViewport } from "./components/ToastViewport";
import { WorkspaceSwitcher } from "./components/WorkspaceSwitcher";
import { SettingsPanel } from "./components/SettingsPanel";
import { toast } from "./components/toast";
import { isPermissionTierId } from "./permissionTiers";
import type { StudioSession } from "./types";

export function App() {
  const [panelOpen, setPanelOpen] = useState(true);
  const paneLayout = usePaneLayout();
  const { viewMode, cycleViewMode } = useViewMode();
  const { diffFocus, toggleDiffFocus } = useDiffFocus();
  const { sideChatOpen, setSideChatOpen, toggleSideChat, closeSideChat, composerSideAsk, toggleComposerSideAsk } = useSideChat();
  const [sideChatSending, setSideChatSending] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const reviewRef = useRef<ReturnType<typeof useWorkspaceReview> | null>(null);
  const runEvidenceRef = useRef<ReturnType<typeof useRunEvidence> | null>(null);

  const bootstrap = useStudioBootstrap({
    // Do NOT auto-open the workspace's latest run here: it pulls ANOTHER session's run into
    // runDetail, so an empty/new conversation would render that run's steps + review bar — the
    // "mystery review line at the top of a new chat". The per-session auto-open effect inside
    // useRunEvidence already opens the run that belongs to the active session's own events.
    onOverviewReady: async () => {
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

  const [paletteOpen, setPaletteOpen] = useState(false);
  const paletteCommands = useMemo<Command[]>(() => {
    const list: Command[] = [];
    for (const session of bootstrap.sessions) {
      if (session.session_id === bootstrap.activeSession?.session_id) continue;
      list.push({ id: `session:${session.session_id}`, label: session.title || "Untitled session", hint: "Switch session", run: () => selectSession(session) });
    }
    if (sessionEvents.isRunning) list.push({ id: "stop", label: "Stop the running task", hint: "Esc", run: () => void sessionEvents.stopRun() });
    list.push(
      { id: "review", label: "Review changes", hint: "Ctrl+Shift+D", run: () => toggleDiffFocus() },
      { id: "panel", label: "Toggle side panel", hint: "Ctrl+\\", run: () => setPanelOpen((open) => !open) },
      { id: "sidebar", label: "Toggle sessions sidebar", hint: "Ctrl+B", run: () => toggleSidebarCollapsed() },
      { id: "sidechat", label: "Toggle Quick ask", hint: "Ctrl+;", run: () => toggleSideChat() },
      { id: "settings", label: "Open Settings", run: () => setSettingsOpen(true) },
      { id: "refresh", label: "Refresh", run: () => void bootstrap.bootstrap() },
    );
    return list;
  }, [bootstrap.sessions, bootstrap.activeSession?.session_id, sessionEvents.isRunning, sessionEvents.stopRun, selectSession, toggleDiffFocus, toggleSidebarCollapsed, toggleSideChat, bootstrap]);

  useStudioKeyboard({
    sessions: bootstrap.sessions,
    activeSessionId: bootstrap.activeSession?.session_id,
    onTogglePanel: () => setPanelOpen((open) => !open),
    onToggleSidebar: toggleSidebarCollapsed,
    onToggleDiffFocus: toggleDiffFocus,
    onToggleSideChat: toggleSideChat,
    onSelectSession: selectSession,
    onOpenPalette: () => setPaletteOpen(true),
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
    const trimmed = action.trim();
    if (/^(review|accept)\b/i.test(trimmed)) {
      await openCurrentReview();
    }
    try {
      await sessionEvents.runRuntimeAction(action);
    } catch (err) {
      toast.error("That action didn't go through. Try again.");
      throw err; // preserve the existing rejection propagation
    }
    // Confirm the terminal action — its button often disappears on success, so a
    // toast is the only post-click acknowledgement the user gets.
    if (/^accept\b/i.test(trimmed)) toast.success("Run finalized — changes are in your workspace.");
  }, [openCurrentReview, sessionEvents]);

  return (
    <div
      className={shellClassName}
      style={{
        ["--sidebar-width" as string]: `${effectiveSidebarWidth}px`,
        ["--panel-width" as string]: `${panelWidth}px`,
      }}
    >
      <MissionPaneHeader
        title={bootstrap.activeSession?.title ?? "New task"}
        settings={bootstrap.settings}
        viewMode={viewMode}
        panelOpen={panelOpen}
        diffFocus={diffFocus}
        loading={bootstrap.loading}
        isRunning={sessionEvents.isRunning}
        connectivity={sessionEvents.connectivity}
        changeCount={review.gitStatus?.change_count ?? review.gitStatus?.changes?.length ?? 0}
        branch={review.gitStatus?.branch}
        onOpenWorkspace={() => bootstrap.setWorkspaceOpen(true)}
        onCycleViewMode={cycleViewMode}
        onTogglePanel={() => setPanelOpen((open) => !open)}
        onToggleDiffFocus={toggleDiffFocus}
        onToggleSideChat={toggleSideChat}
        onOpenSettings={() => setSettingsOpen(true)}
        sideChatOpen={sideChatOpen || composerSideAsk}
        onRefresh={() => void bootstrap.bootstrap()}
      />
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
      <main className="missionPane">
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
          loading={bootstrap.loading}
        />
        <Composer
          onSend={sessionEvents.sendGoal}
          onSideAsk={sendSideAsk}
          sideAsk={composerSideAsk}
          onSideAskToggle={toggleComposerSideAsk}
          promptSignal={bootstrap.promptSignal}
          viewMode={viewMode}
          initialPermissionMode={isPermissionTierId(bootstrap.settings?.permissionMode) ? bootstrap.settings?.permissionMode : undefined}
          isRunning={sessionEvents.isRunning}
          onStop={sessionEvents.stopRun}
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
      <ToastViewport />
      <WorkspaceSwitcher
        open={bootstrap.workspaceOpen}
        currentWorkspace={bootstrap.settings?.workspace ?? ""}
        onClose={() => bootstrap.setWorkspaceOpen(false)}
        onOpened={() => void bootstrap.bootstrap()}
      />
      <SettingsPanel
        open={settingsOpen}
        settings={bootstrap.settings}
        overview={bootstrap.overview}
        onClose={() => setSettingsOpen(false)}
        onChangeWorkspace={() => { setSettingsOpen(false); bootstrap.setWorkspaceOpen(true); }}
        onSaved={(next) => bootstrap.setSettings(next)}
      />
      <CommandPalette open={paletteOpen} commands={paletteCommands} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
