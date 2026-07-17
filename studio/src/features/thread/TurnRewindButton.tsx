import React, { useState } from "react";
import { History, RotateCcw } from "lucide-react";
import type { AnyRecord, RunDetailPayload } from "../../types";
import type { StudioViewMode } from "../../hooks/useViewMode";
import { api } from "../../api";
import { toast } from "../../components/toast";
import { planTurnRewind } from "./turnRewind";

type SnapshotPreview = {
  changed: { path: string; additions: number; deletions: number }[];
  toDelete: string[];
  clean: boolean;
};

function parsePreview(payload: AnyRecord): SnapshotPreview {
  return {
    changed: Array.isArray(payload.changed) ? (payload.changed as SnapshotPreview["changed"]) : [],
    toDelete: Array.isArray(payload.to_delete) ? (payload.to_delete as string[]) : [],
    clean: payload.clean === true,
  };
}

/**
 * G7 rewind 文件回滚 — the turn menu grows the mainstream second action: besides continuing the
 * conversation from here, restore the WORKSPACE FILES to this turn's shadow snapshot. The restore
 * is confirmed against a real diff preview (never blind — a later manual edit must be visible
 * before it gets overwritten), states honestly that shell side effects are NOT rolled back, and
 * the BFF auto-snapshots the current state first so the rewind itself is undoable.
 */
export function TurnRewindButton({
  turnIndex,
  isLast,
  isRunning,
  runDetail,
  viewMode,
  onRewind,
  snapshotHash = null,
  onFilesRestored,
}: {
  turnIndex: number;
  isLast: boolean;
  isRunning: boolean;
  runDetail: RunDetailPayload | null | undefined;
  viewMode: StudioViewMode;
  onRewind: (turnIndex: number, action: string) => Promise<void>;
  /** This turn's shadow workspace snapshot; null on non-git workspaces / older transcripts. */
  snapshotHash?: string | null;
  /** Called after a successful file restore so the host can refresh git status / diff views. */
  onFilesRestored?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  // WHICH action is running, not just whether one is. A shared boolean made every button report
  // the same progress: starting a conversation rewind flipped the neighbouring file button to
  // "读取差异…", telling the user a diff was loading when it was not.
  const [busyAction, setBusyAction] = useState<"rewind" | "preview" | "restore" | null>(null);
  const [preview, setPreview] = useState<SnapshotPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const plan = planTurnRewind(runDetail, isRunning);

  if (isLast) return null;
  if (viewMode === "focus") return null;

  const busy = busyAction !== null;
  const disabled = plan.disabled || busy;

  async function confirmRewind() {
    if (!plan.action || disabled) return;
    setBusyAction("rewind");
    try {
      await onRewind(turnIndex, plan.action);
      close();
    } finally {
      setBusyAction(null);
    }
  }

  function close() {
    setConfirming(false);
    setPreview(null);
    setPreviewError(null);
  }

  async function loadFilePreview() {
    if (!snapshotHash || busy) return;
    setBusyAction("preview");
    setPreviewError(null);
    try {
      const result = await api.snapshotDiff(snapshotHash);
      if (result?.ok) setPreview(parsePreview(result));
      else setPreviewError(String(result?.error || "无法读取快照差异。"));
    } catch {
      setPreviewError("无法读取快照差异——请重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function confirmRestoreFiles() {
    if (!snapshotHash || busy) return;
    setBusyAction("restore");
    try {
      const result = await api.restoreSnapshot(snapshotHash);
      if (result?.ok) {
        toast.success(
          `文件已回滚到本轮完成时的状态${result.safety_snapshot ? "（回滚前已自动快照当前状态）" : ""}。`,
        );
        onFilesRestored?.();
        close();
      } else {
        toast.error(String(result?.error || "回滚失败——请重试。"));
      }
    } catch {
      toast.error("回滚失败——请重试。");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="turnRewindWrap">
      {!confirming ? (
        <button
          type="button"
          className="turnRewindButton"
          title={plan.disabledReason ?? plan.reason}
          disabled={disabled}
          onClick={() => setConfirming(true)}
        >
          <RotateCcw size={12} />
          <span>{plan.label}</span>
        </button>
      ) : preview || previewError ? (
        <div className="turnRewindConfirm" role="dialog" aria-label="确认回滚文件">
          {previewError ? (
            <p className="turnRewindNote bad">{previewError}</p>
          ) : preview?.clean ? (
            <p>工作区与本轮完成时一致——没有需要回滚的文件改动。</p>
          ) : (
            <>
              <p>把工作区文件回滚到本轮完成时的状态，将会：</p>
              <ul className="turnRewindFileList">
                {preview?.changed.map((row) => (
                  <li key={row.path}>
                    <span className="turnRewindFilePath">{row.path}</span>
                    <span className="turnRewindDelta">
                      {row.additions > 0 && <em className="deltaAdd">+{row.additions}</em>}
                      {row.deletions > 0 && <em className="deltaDel">-{row.deletions}</em>}
                    </span>
                  </li>
                ))}
                {preview?.toDelete.map((file) => (
                  <li key={file}>
                    <span className="turnRewindFilePath">{file}</span>
                    <span className="turnRewindDelta">
                      <em className="deltaDel">删除</em>
                    </span>
                  </li>
                ))}
              </ul>
              <p className="turnRewindNote">
                只回滚文件内容——shell
                命令的副作用（安装、网络调用等）不会撤销；回滚前会自动快照当前状态，可再次回滚回来。
              </p>
            </>
          )}
          <div className="turnRewindConfirmActions">
            <button type="button" onClick={close} disabled={busy}>
              取消
            </button>
            {!previewError && !preview?.clean && (
              <button
                type="button"
                className="primary"
                onClick={() => void confirmRestoreFiles()}
                disabled={busy}
              >
                {busyAction === "restore" ? "回滚中…" : "回滚文件"}
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="turnRewindConfirm" role="dialog" aria-label="确认回退">
          <p>{plan.reason}</p>
          <div className="turnRewindConfirmActions">
            <button type="button" onClick={close} disabled={busy}>
              取消
            </button>
            <button
              type="button"
              className="turnRewindFiles"
              title={
                snapshotHash
                  ? "把工作区文件回滚到本轮完成时的状态（先看差异再确认）"
                  : "本轮没有文件快照（非 Git 仓库或早于快照功能的会话）——只能从对话接着做"
              }
              disabled={busy || !snapshotHash}
              onClick={() => void loadFilePreview()}
            >
              <History size={12} />
              {busyAction === "preview" ? "读取差异…" : "回滚文件…"}
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => void confirmRewind()}
              disabled={busy || plan.disabled}
            >
              {busyAction === "rewind" ? "执行中…" : plan.label}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
