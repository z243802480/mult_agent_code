import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  FilePreview,
  GitDiffPayload,
  GitStatusPayload,
  StudioEvent,
  StudioSession,
} from "../types";
import type { DiffLayout, DiffStage } from "../components/DiffPreview";
import { api } from "../api";
import { buildTurnDiffScopes } from "../turnDiff";

export function useWorkspaceReview(
  activeSession: StudioSession | null,
  events: StudioEvent[],
  selectedRunId: string | null,
  setRunDetail: (detail: Awaited<ReturnType<typeof api.runDetail>> | null) => void,
) {
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatusPayload | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  const [gitSelectedPath, setGitSelectedPath] = useState<string | null>(null);
  const [gitDiffPayload, setGitDiffPayload] = useState<GitDiffPayload | null>(null);
  const [diffScopeId, setDiffScopeId] = useState("current");
  const [diffStage, setDiffStage] = useState<DiffStage>("all");
  const [diffLayout, setDiffLayout] = useState<DiffLayout>("unified");
  const [gitActionLoading, setGitActionLoading] = useState(false);
  const [compactLoading, setCompactLoading] = useState(false);
  const [contextSectionId, setContextSectionId] = useState<string | null>(null);

  const turnDiffScopes = useMemo(() => buildTurnDiffScopes(events), [events]);

  const refreshGitStatus = useCallback(async () => {
    setGitLoading(true);
    try {
      const status = await api.gitStatus();
      setGitStatus(status);
      return status;
    } catch {
      const status: GitStatusPayload = {
        ok: false,
        available: false,
        reason: "Could not load git status.",
      };
      setGitStatus(status);
      return status;
    } finally {
      setGitLoading(false);
    }
  }, []);

  async function openFileChange(pathValue: string, stage: DiffStage = diffStage) {
    setGitSelectedPath(pathValue);
    try {
      const diff = await api.gitDiff(pathValue, stage);
      setGitDiffPayload(diff);
      const diffText = String(diff.diff ?? "");
      if (diff.ok && diffText && !diffText.includes("(no diff")) {
        setPreview({
          ok: true,
          path: diff.path ?? pathValue,
          content: diffText,
        });
        return;
      }
      setPreview(await api.previewFile(pathValue));
    } catch (err) {
      setGitDiffPayload(null);
      setPreview({ ok: false, error: String((err as Error).message || err) });
    }
  }

  async function openGitDiff(pathValue: string) {
    await openFileChange(pathValue);
  }

  async function openFile(path: string) {
    setGitSelectedPath(null);
    setPreview(await api.previewFile(path));
  }

  function selectTurnDiff(turnIndex: number) {
    const scope = turnDiffScopes.find((item) => item.turnIndex === turnIndex);
    if (scope) {
      setDiffScope(scope.id);
    } else {
      setDiffScope(`turn-chrono-${turnIndex}`);
    }
    const firstPath = scope?.files[0]?.path;
    if (firstPath) {
      void openFileChange(firstPath);
    }
  }

  async function persistSessionUiState(nextScopeId = diffScopeId, nextStage = diffStage, nextLayout = diffLayout) {
    if (!activeSession) return;
    await api.updateSession(activeSession.session_id, {
      ui_state: {
        diffScopeId: nextScopeId,
        diffStage: nextStage,
        diffLayout: nextLayout,
      },
    }).catch(() => {});
  }

  function setDiffScope(scopeId: string) {
    setDiffScopeId(scopeId);
    void persistSessionUiState(scopeId);
  }

  function setDiffStageAndReload(stage: DiffStage) {
    setDiffStage(stage);
    void persistSessionUiState(diffScopeId, stage);
    if (gitSelectedPath) void openFileChange(gitSelectedPath, stage);
  }

  function setDiffLayoutMode(layout: DiffLayout) {
    setDiffLayout(layout);
    void persistSessionUiState(diffScopeId, diffStage, layout);
  }

  async function stageSelectedFile() {
    if (!gitSelectedPath) return;
    setGitActionLoading(true);
    try {
      await api.gitStage(gitSelectedPath);
      await refreshGitStatus();
      await openFileChange(gitSelectedPath, diffStage);
    } finally {
      setGitActionLoading(false);
    }
  }

  async function discardSelectedFile() {
    if (!gitSelectedPath) return;
    const ok = window.confirm(`Discard uncommitted changes in ${gitSelectedPath}?`);
    if (!ok) return;
    setGitActionLoading(true);
    try {
      await api.gitDiscard(gitSelectedPath);
      await refreshGitStatus();
      await openFileChange(gitSelectedPath, diffStage);
    } finally {
      setGitActionLoading(false);
    }
  }

  async function compactContext() {
    if (!activeSession) return;
    const ok = window.confirm("Compact session context? Older turns may be summarized.");
    if (!ok) return;
    setCompactLoading(true);
    try {
      await api.runtimeAction(activeSession.session_id, "compact", "ask");
      if (selectedRunId) {
        setRunDetail(await api.runDetail(selectedRunId));
      }
    } finally {
      setCompactLoading(false);
    }
  }

  function applySessionUiState(session: StudioSession) {
    const ui = session.ui_state ?? {};
    setDiffScopeId(String(ui.diffScopeId || "current"));
    setDiffStage(String(ui.diffStage || "all") as DiffStage);
    setDiffLayout(String(ui.diffLayout || "unified") as DiffLayout);
  }

  useEffect(() => {
    if (diffScopeId === "current") return;
    if (!turnDiffScopes.some((scope) => scope.id === diffScopeId)) {
      setDiffScopeId("current");
    }
  }, [diffScopeId, turnDiffScopes]);

  return {
    preview,
    gitStatus,
    gitLoading,
    gitSelectedPath,
    gitDiffPayload,
    diffScopeId,
    diffStage,
    diffLayout,
    gitActionLoading,
    compactLoading,
    contextSectionId,
    turnDiffScopes,
    refreshGitStatus,
    openFileChange,
    openGitDiff,
    openFile,
    selectTurnDiff,
    setDiffScope,
    setDiffStageAndReload,
    setDiffLayoutMode,
    stageSelectedFile,
    discardSelectedFile,
    compactContext,
    setContextSectionId,
    applySessionUiState,
  };
}
