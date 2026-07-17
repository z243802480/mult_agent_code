import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { shouldResetForSession } from "./session/sessionSelection";
import { api } from "./api";
import { Banner } from "./components/Shared";
import { Sidebar } from "./components/Sidebar";
import { Thread } from "./components/Thread";
import { SidePanel } from "./components/SidePanel";
import { Composer } from "./components/Composer";
import { MissionPaneHeader } from "./layout/MissionPaneHeader";
import { cleanSessionTitle } from "./features/sidebar/sessionListUtils";
import { useNotifications } from "./hooks/useNotifications";
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
import { isPermissionTierId, legacyPermission, resolvePermissionTier } from "./permissionTiers";
import { useTheme } from "./hooks/useTheme";
import { DiffCommentTray } from "./components/DiffCommentTray";
import { setDiffCommentSession } from "./session/diffComments";
import { setPlanCommentSession } from "./session/planComments";
import { buildAiReviewPrompt } from "./session/aiReview";
import type { StudioSession } from "./types";

export function App() {
  const [panelOpen, setPanelOpen] = useState(true);
  // Header context ring → open the panel focused on the Context tab (transient tab focus).
  const [panelTabSignal, setPanelTabSignal] = useState<{
    id: number;
    tab: "preview" | "changes" | "context" | "agents" | "evidence";
  } | null>(null);
  const openContextPanel = useCallback(() => {
    setPanelOpen(true);
    setPanelTabSignal((signal) => ({ id: (signal?.id ?? 0) + 1, tab: "context" }));
  }, []);
  const paneLayout = usePaneLayout();
  const { viewMode, cycleViewMode } = useViewMode();
  const { theme, setTheme } = useTheme();
  const { diffFocus, toggleDiffFocus } = useDiffFocus();
  const {
    sideChatOpen,
    setSideChatOpen,
    toggleSideChat,
    closeSideChat,
    composerSideAsk,
    toggleComposerSideAsk,
  } = useSideChat();
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

  // ADR-0029 ①: whether the server has mid-run steer enabled. Gates the Composer's "insert now"
  // behaviour so we only promise mid-run delivery when the runtime will actually honour it.
  const [midRunSteer, setMidRunSteer] = useState(false);
  useEffect(() => {
    api
      .health()
      .then((h) => setMidRunSteer(Boolean(h?.mid_run_steer)))
      .catch(() => setMidRunSteer(false));
  }, []);

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

  // G4/G6 评论即指令: point the shared pending-feedback stores (diff line comments + plan step
  // comments) at the active session so comments written anywhere stay per-session.
  useEffect(() => {
    setDiffCommentSession(bootstrap.activeSession?.session_id ?? "");
    setPlanCommentSession(bootstrap.activeSession?.session_id ?? "");
  }, [bootstrap.activeSession?.session_id]);

  // G5 AI 自审: assemble the current workspace diff into a read-only chat-mode review request.
  // Bounded (files + chars) with the truncation stated in the prompt — the verdict must never
  // claim coverage it didn't have. The reply is a normal turn; the changes pane anchors it.
  const [aiReviewSending, setAiReviewSending] = useState(false);
  async function startAiReview() {
    if (sessionEvents.isRunning || aiReviewSending) return;
    setAiReviewSending(true);
    try {
      const status = await review.refreshGitStatus();
      const changes = (status?.changes ?? []).map((change) => change.path).filter(Boolean);
      if (!changes.length) {
        toast.error("工作区没有可评审的改动。");
        return;
      }
      const diffs: { path: string; diff: string }[] = [];
      let total = 0;
      let truncated = false;
      for (const filePath of changes) {
        if (diffs.length >= 12 || total > 24_000) {
          truncated = true;
          break;
        }
        try {
          const payload = await api.gitDiff(filePath, "all");
          const text = String(payload.diff ?? "");
          if (!text.trim() || text.includes("(no diff")) continue;
          diffs.push({ path: filePath, diff: text.slice(0, 8_000) });
          total += Math.min(text.length, 8_000);
        } catch {
          // Unreadable file (binary/permission) — review what we can, honestly bounded.
        }
      }
      if (!diffs.length) {
        toast.error("没有可评审的文本改动。");
        return;
      }
      const tier = resolvePermissionTier(bootstrap.settings?.permissionMode);
      await sessionEvents.sendGoal(
        buildAiReviewPrompt(diffs, { truncated }),
        "chat",
        legacyPermission(tier),
        tier,
      );
    } finally {
      setAiReviewSending(false);
    }
  }

  // OS notifications ("done and you're not looking") + favicon status dot (G1).
  useNotifications({
    isRunning: sessionEvents.isRunning,
    waiting: sessionEvents.waiting,
    interrupted: sessionEvents.interrupted,
    sessionTitle: bootstrap.activeSession
      ? cleanSessionTitle(bootstrap.activeSession.title)
      : "新任务",
  });

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

  const selectSession = useCallback(
    (session: StudioSession) => {
      // Both halves of this rule are production regressions; shouldResetForSession documents why.
      const reset = shouldResetForSession(bootstrap.activeSession?.session_id, session.session_id);
      bootstrap.setActiveSession(session);
      if (reset) {
        runEvidence.clearSelection();
        sessionEvents.clearEvents();
      }
      // Unconditional: bootstrap auto-selects a session without coming through here, so this is
      // ui_state's only read-back path.
      review.applySessionUiState(session);
    },
    [bootstrap, runEvidence, sessionEvents, review],
  );

  const [paletteOpen, setPaletteOpen] = useState(false);
  const paletteCommands = useMemo<Command[]>(() => {
    const list: Command[] = [];
    for (const session of bootstrap.sessions) {
      if (session.session_id === bootstrap.activeSession?.session_id) continue;
      list.push({
        id: `session:${session.session_id}`,
        label: session.title || "未命名会话",
        hint: "切换会话",
        run: () => selectSession(session),
      });
    }
    if (sessionEvents.isRunning)
      list.push({
        id: "stop",
        label: "停止运行中的任务",
        hint: "Esc",
        run: () => void sessionEvents.stopRun(),
      });
    list.push(
      { id: "review", label: "查看改动", hint: "Ctrl+Shift+D", run: () => toggleDiffFocus() },
      {
        id: "panel",
        label: "切换侧栏面板",
        hint: "Ctrl+\\",
        run: () => setPanelOpen((open) => !open),
      },
      {
        id: "sidebar",
        label: "切换会话侧边栏",
        hint: "Ctrl+B",
        run: () => toggleSidebarCollapsed(),
      },
      { id: "sidechat", label: "切换快速提问", hint: "Ctrl+;", run: () => toggleSideChat() },
      { id: "settings", label: "打开设置", run: () => setSettingsOpen(true) },
      { id: "refresh", label: "刷新", run: () => void bootstrap.bootstrap() },
    );
    return list;
  }, [
    bootstrap.sessions,
    bootstrap.activeSession?.session_id,
    sessionEvents.isRunning,
    sessionEvents.stopRun,
    selectSession,
    toggleDiffFocus,
    toggleSidebarCollapsed,
    toggleSideChat,
    bootstrap,
  ]);

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

  const shellClassName = useMemo(
    () =>
      [
        "appShell",
        panelOpen ? "panelOpen" : "panelCollapsed",
        sidebarCollapsed ? "sidebarCollapsed" : "",
        diffFocus ? "diffFocus" : "",
        `view-${viewMode}`,
      ]
        .filter(Boolean)
        .join(" "),
    [panelOpen, sidebarCollapsed, diffFocus, viewMode],
  );

  const sendSideAsk = useCallback(
    async (message: string) => {
      setSideChatOpen(true);
      setSideChatSending(true);
      try {
        await sessionEvents.sendSideAsk(message);
      } finally {
        setSideChatSending(false);
      }
    },
    [sessionEvents, setSideChatOpen],
  );

  const resolveDecision = useCallback(
    (runId: string, decisionId: string, optionId: string) =>
      sessionEvents.resolveDecision(runId, decisionId, optionId, runEvidence.setRunDetail),
    [sessionEvents, runEvidence.setRunDetail],
  );

  const answerDecision = useCallback(
    (runId: string, decisionId: string, answer: string) =>
      sessionEvents.answerDecision(runId, decisionId, answer, runEvidence.setRunDetail),
    [sessionEvents, runEvidence.setRunDetail],
  );

  const onTurnRewind = useCallback(
    async (_turnIndex: number, action: string) => {
      await sessionEvents.runRuntimeAction(action);
    },
    [sessionEvents],
  );

  const openReviewFile = useCallback(
    async (pathValue: string) => {
      setPanelOpen(true);
      await review.refreshGitStatus();
      await review.openFileChange(pathValue);
    },
    [review],
  );

  const openTurnReview = useCallback(
    (turnIndex: number) => {
      setPanelOpen(true);
      void review.refreshGitStatus();
      review.selectTurnDiff(turnIndex);
    },
    [review],
  );

  // Inline per-turn Keep/Revert (I11) — real git stage / checkout, with honest toasts.
  const onFileAccept = useCallback(
    async (pathValue: string): Promise<boolean> => {
      const ok = await review.acceptFileChange(pathValue);
      if (ok) toast.success("已保留——文件已暂存。");
      else toast.error("无法暂存该文件。请尝试查看面板。");
      return ok;
    },
    [review],
  );

  const onFileRevert = useCallback(
    async (pathValue: string): Promise<boolean> => {
      const ok = await review.revertFileChange(pathValue);
      // Accurate for both cases: a tracked file reverts to its committed content, an agent-CREATED
      // (untracked) file is removed — "恢复到上次提交" was wrong (and confusing) for the created case.
      if (ok) toast.success("已还原——已撤销该文件的改动。");
      else toast.error("无法还原该文件。请尝试查看面板。");
      return ok;
    },
    [review],
  );

  const openCurrentReview = useCallback(async () => {
    setPanelOpen(true);
    const status = await review.refreshGitStatus();
    const firstPath = review.gitSelectedPath ?? status.changes?.[0]?.path;
    if (firstPath) {
      await review.openFileChange(firstPath);
    }
  }, [review]);

  const runRuntimeAction = useCallback(
    async (action: string) => {
      const trimmed = action.trim();
      if (/^(review|accept)\b/i.test(trimmed)) {
        await openCurrentReview();
      }
      // runRuntimeAction now surfaces its own failure toast and returns the server result. Only claim
      // the terminal action succeeded when the server actually STARTED it (started===true) — previously
      // this fired a green "已最终确认" toast even when the server had merely queued a second approval
      // and NOT accepted, so the user was told the run was finalized when it was not.
      const result = await sessionEvents.runRuntimeAction(action);
      if (!result?.ok || result?.started === false) return;
      if (/^accept\b/i.test(trimmed)) toast.success("运行已最终确认——改动已进入你的工作区。");
    },
    [openCurrentReview, sessionEvents],
  );

  return (
    <div
      className={shellClassName}
      style={{
        ["--sidebar-width" as string]: `${effectiveSidebarWidth}px`,
        ["--panel-width" as string]: `${panelWidth}px`,
      }}
    >
      <MissionPaneHeader
        // Same mojibake guard the sidebar uses — the header was the third leak of raw legacy-CLI
        // titles (misdecoded console bytes rendered as debris in the most prominent spot on screen).
        title={
          bootstrap.activeSession ? cleanSessionTitle(bootstrap.activeSession.title) : "新任务"
        }
        settings={bootstrap.settings}
        viewMode={viewMode}
        panelOpen={panelOpen}
        diffFocus={diffFocus}
        loading={bootstrap.loading}
        isRunning={sessionEvents.isRunning}
        interrupted={sessionEvents.interrupted}
        waiting={sessionEvents.waiting}
        connectivity={sessionEvents.connectivity}
        changeCount={review.gitStatus?.change_count ?? review.gitStatus?.changes?.length ?? 0}
        branch={review.gitStatus?.branch}
        runDetail={runEvidence.runDetail}
        onOpenContext={openContextPanel}
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
        onNew={() =>
          void bootstrap.newSession(() => {
            runEvidence.clearSelection();
            sessionEvents.clearEvents();
          })
        }
        onDelete={(session) =>
          void bootstrap.deleteSession(session, () => {
            runEvidence.clearSelection();
            sessionEvents.clearEvents();
          })
        }
        onArchive={(session, archived) => {
          void (async () => {
            const result = await api
              .updateSession(session.session_id, { archived })
              .catch(() => null);
            if (!result?.ok) return;
            bootstrap.setSessions(
              bootstrap.sessions.map((item) =>
                item.session_id === session.session_id ? result.session : item,
              ),
            );
          })();
        }}
        onRename={async (session, title) => {
          const result = await api.updateSession(session.session_id, { title });
          bootstrap.setSessions(
            bootstrap.sessions.map((item) =>
              item.session_id === session.session_id ? result.session : item,
            ),
          );
          if (bootstrap.activeSession?.session_id === session.session_id) {
            bootstrap.setActiveSession(result.session);
          }
        }}
        onImportFile={async (file) => {
          let bundle: unknown;
          try {
            bundle = JSON.parse(await file.text());
          } catch {
            toast.error("无法读取该文件——需要 Studio 会话 .json 备份。");
            return;
          }
          const res = await api.importSession(bundle).catch(() => null);
          if (!res?.ok || !res.session) {
            toast.error(res?.error ? `导入失败：${res.error}` : "导入失败——不是有效的会话备份。");
            return;
          }
          const refreshed = await api.sessions();
          bootstrap.setSessions(refreshed.sessions ?? []);
          selectSession(res.session);
          toast.success(`已导入“${res.session.title || "会话"}”。`);
        }}
        viewMode={viewMode}
      />
      {!sidebarCollapsed && (
        <div
          className="paneSplitter sidebarSplitter"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整侧边栏宽度"
          title="拖动调整宽度 · 双击重置"
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
          interrupted={sessionEvents.interrupted}
          onSelect={runEvidence.selectEvent}
          onPrompt={bootstrap.pushPrompt}
          onPermit={sessionEvents.permitJob}
          onRuntimeAction={runRuntimeAction}
          onOpenReview={openCurrentReview}
          onResolveDecision={resolveDecision}
          onAnswerDecision={answerDecision}
          pendingTurn={sessionEvents.pendingTurn}
          overview={bootstrap.overview}
          runDetail={runEvidence.runDetail}
          workspaceChangeCount={
            review.gitStatus?.change_count ?? review.gitStatus?.changes?.length ?? 0
          }
          onFileChangeClick={(pathValue) => void openReviewFile(pathValue)}
          onFileAccept={onFileAccept}
          onFileRevert={onFileRevert}
          onTurnDiffSelect={openTurnReview}
          turnDiffLabel={(turnIndex) =>
            review.turnDiffScopes.find((scope) => scope.turnIndex === turnIndex)?.label ??
            `T${turnIndex}`
          }
          onAggregateDiffClick={openTurnReview}
          viewMode={viewMode}
          onTurnRewind={onTurnRewind}
          onFilesRestored={() => void review.refreshGitStatus()}
          loading={bootstrap.loading}
        />
        <DiffCommentTray
          isRunning={sessionEvents.isRunning}
          midRunSteer={midRunSteer}
          onSteer={sessionEvents.steerRun}
          onSend={(message) => {
            const tier = resolvePermissionTier(bootstrap.settings?.permissionMode);
            return sessionEvents.sendGoal(message, "auto", legacyPermission(tier), tier);
          }}
        />
        <Composer
          key={bootstrap.activeSession?.session_id ?? "no-session"}
          sessionId={bootstrap.activeSession?.session_id}
          onSend={sessionEvents.sendGoal}
          onSideAsk={sendSideAsk}
          sideAsk={composerSideAsk}
          onSideAskToggle={toggleComposerSideAsk}
          promptSignal={bootstrap.promptSignal}
          viewMode={viewMode}
          initialPermissionMode={
            isPermissionTierId(bootstrap.settings?.permissionMode)
              ? bootstrap.settings?.permissionMode
              : undefined
          }
          isRunning={sessionEvents.isRunning}
          runStateKnown={sessionEvents.runStateKnown}
          onStop={sessionEvents.stopRun}
          onPause={sessionEvents.pauseRun}
          onSteer={sessionEvents.steerRun}
          midRunSteer={midRunSteer}
          files={bootstrap.files}
        />
      </main>
      {panelOpen && (
        <>
          <div
            className="paneSplitter panelSplitter"
            role="separator"
            aria-orientation="vertical"
            aria-label="调整侧栏面板宽度"
            title="拖动调整宽度 · 双击重置"
            onMouseDown={startPanelDrag}
            onDoubleClick={resetPanel}
          />
          <SidePanel
            event={runEvidence.selectedEvent}
            events={sessionEvents.events}
            tabSignal={panelTabSignal}
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
            onAiReview={() => void startAiReview()}
            aiReviewBusy={sessionEvents.isRunning || aiReviewSending}
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
        theme={theme}
        onThemeChange={setTheme}
        onClose={() => setSettingsOpen(false)}
        onChangeWorkspace={() => {
          setSettingsOpen(false);
          bootstrap.setWorkspaceOpen(true);
        }}
        onSaved={(next) => bootstrap.setSettings(next)}
      />
      <CommandPalette
        open={paletteOpen}
        commands={paletteCommands}
        onClose={() => setPaletteOpen(false)}
      />
    </div>
  );
}
