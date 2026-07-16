import React, { useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, Download, FileClock, Pencil, Trash2, Upload } from "lucide-react";
import { api } from "../../api";
import type { StudioSession } from "../../types";
import type { SessionListFilter } from "./sessionListUtils";
import {
  cleanSessionTitle,
  filterSessions,
  groupSessionsByDate,
  searchSessions,
  sessionHint,
  sessionPreview,
} from "./sessionListUtils";

type SessionListProps = {
  sessions: StudioSession[];
  active: StudioSession | null;
  isRunning: boolean;
  filter: SessionListFilter;
  onFilterChange: (filter: SessionListFilter) => void;
  onSelect: (session: StudioSession) => void;
  onDelete: (session: StudioSession) => void;
  onRename: (session: StudioSession, title: string) => Promise<void>;
  onArchive?: (session: StudioSession, archived: boolean) => void;
  onImportFile?: (file: File) => void;
  compact?: boolean;
};

export function SessionList({
  sessions,
  active,
  isRunning,
  filter,
  onFilterChange,
  onSelect,
  onDelete,
  onRename,
  onArchive,
  onImportFile,
  compact = false,
}: SessionListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [query, setQuery] = useState("");
  const importInputRef = useRef<HTMLInputElement>(null);

  const visibleSessions = useMemo(
    () => searchSessions(filterSessions(sessions, filter), query),
    [sessions, filter, query],
  );
  const groups = useMemo(() => groupSessionsByDate(visibleSessions), [visibleSessions]);

  async function commitRename(session: StudioSession) {
    const next = draftTitle.trim();
    setEditingId(null);
    if (!next || next === session.title) return;
    await onRename(session, next);
  }

  return (
    <nav className="sessionList" aria-label="会话">
      <div className="sessionListHeader">
        <div className="sessionListTitleRow">
          <p className="sideTitle">任务</p>
          {onImportFile && (
            <>
              <button
                type="button"
                className="sessionImportButton"
                title="导入会话备份 (.json)"
                aria-label="导入会话备份"
                onClick={() => importInputRef.current?.click()}
              >
                <Upload size={13} />
              </button>
              <input
                ref={importInputRef}
                type="file"
                accept="application/json,.json"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onImportFile(file);
                  event.target.value = ""; // allow re-importing the same file
                }}
              />
            </>
          )}
        </div>
        <div className="sessionFilterTabs" role="tablist" aria-label="会话筛选">
          {(["all", "recent", "archived"] as SessionListFilter[]).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              className={filter === value ? "sessionFilterTab active" : "sessionFilterTab"}
              aria-selected={filter === value}
              onClick={() => onFilterChange(value)}
            >
              {value === "all" ? "全部" : value === "recent" ? "最近" : "已归档"}
            </button>
          ))}
        </div>
        <input
          type="search"
          className="sessionSearchInput"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索任务…"
          aria-label="搜索会话"
        />
      </div>
      {groups.length === 0 && (
        <p className="sessionListEmpty muted">
          {query.trim()
            ? `没有匹配“${query.trim()}”的任务。`
            : filter === "recent"
              ? "最近 7 天没有任务。"
              : filter === "archived"
                ? "没有已归档的任务。"
                : "还没有任务。"}
        </p>
      )}
      {groups.map((group) => (
        <section key={group.id} className="sessionGroup">
          {!compact && <p className="sessionGroupLabel">{group.label}</p>}
          {group.sessions.map((session) => (
            <SessionRow
              key={session.session_id}
              session={session}
              isActive={active?.session_id === session.session_id}
              showLive={
                session.run_status === "running" ||
                (active?.session_id === session.session_id && isRunning)
              }
              onArchive={onArchive}
              compact={compact}
              editingId={editingId}
              draftTitle={draftTitle}
              exportHref={api.exportUrl(session.session_id)}
              onSelect={onSelect}
              onDelete={onDelete}
              onStartRename={(item) => {
                setEditingId(item.session_id);
                setDraftTitle(String(item.title || ""));
              }}
              onDraftChange={setDraftTitle}
              onCommitRename={() => void commitRename(session)}
              onCancelRename={() => setEditingId(null)}
            />
          ))}
        </section>
      ))}
    </nav>
  );
}

type SessionRowProps = {
  session: StudioSession;
  isActive: boolean;
  showLive: boolean;
  onArchive?: (session: StudioSession, archived: boolean) => void;
  compact?: boolean;
  editingId: string | null;
  draftTitle: string;
  exportHref: string;
  onSelect: (session: StudioSession) => void;
  onDelete: (session: StudioSession) => void;
  onStartRename: (session: StudioSession) => void;
  onDraftChange: (value: string) => void;
  onCommitRename: () => void;
  onCancelRename: () => void;
};

function SessionRow({
  session,
  isActive,
  showLive,
  onArchive,
  compact = false,
  editingId,
  draftTitle,
  exportHref,
  onSelect,
  onDelete,
  onStartRename,
  onDraftChange,
  onCommitRename,
  onCancelRename,
}: SessionRowProps) {
  const title = cleanSessionTitle(String(session.title || "未命名"));
  const preview = sessionPreview(session);
  const hint = sessionHint(session, title, preview);

  return (
    <div className={isActive ? "sessionRow active" : "sessionRow"}>
      {editingId === session.session_id ? (
        <input
          className="sessionRenameInput"
          value={draftTitle}
          autoFocus
          onChange={(event) => onDraftChange(event.target.value)}
          onBlur={onCommitRename}
          onKeyDown={(event) => {
            if (event.key === "Enter") onCommitRename();
            if (event.key === "Escape") onCancelRename();
          }}
        />
      ) : (
        <button
          className="session sessionFlat"
          onClick={() => onSelect(session)}
          title={hint || title}
        >
          <span className="sessionTitleRow">
            {showLive ? (
              <span className="sessionLiveDot" aria-label="运行中" />
            ) : session.run_status === "failed" && !isActive ? (
              // The session's latest job settled red while you were elsewhere — a quiet attention
              // dot until the job registry's retention window prunes it (or you open the session).
              <span className="sessionStatusDot failed" aria-label="刚失败" title="刚失败" />
            ) : session.run_status === "completed" && !isActive ? (
              <span className="sessionStatusDot done" aria-label="刚完成" title="刚完成" />
            ) : null}
            <span className="sessionTitleText">{title}</span>
          </span>
          {preview && !isActive && !compact && <small className="sessionPreview">{preview}</small>}
        </button>
      )}
      <button
        className="sessionRename"
        title="重命名会话"
        aria-label="重命名会话"
        onClick={(event) => {
          event.stopPropagation();
          onStartRename(session);
        }}
      >
        <Pencil size={13} />
      </button>
      <a
        className="sessionExport"
        href={exportHref}
        download
        title="导出(备份)会话"
        aria-label="导出会话备份"
        onClick={(event) => event.stopPropagation()}
      >
        <Download size={13} />
      </a>
      <a
        className="sessionExport"
        href={`${exportHref}.html`}
        download
        title="导出回放页(自包含 HTML·可转发复盘)"
        aria-label="导出会话回放页"
        onClick={(event) => event.stopPropagation()}
      >
        <FileClock size={13} />
      </a>
      {onArchive && (
        <button
          className="sessionArchive"
          title={session.archived_at ? "取消归档" : "归档会话"}
          aria-label={session.archived_at ? "取消归档" : "归档会话"}
          onClick={(event) => {
            event.stopPropagation();
            onArchive(session, !session.archived_at);
          }}
        >
          {session.archived_at ? <ArchiveRestore size={13} /> : <Archive size={13} />}
        </button>
      )}
      <button
        className="sessionDelete"
        title="删除会话"
        aria-label="删除会话"
        onClick={(event) => {
          event.stopPropagation();
          onDelete(session);
        }}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}
