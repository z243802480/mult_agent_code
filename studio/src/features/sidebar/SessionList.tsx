import React, { useMemo, useRef, useState } from "react";
import { Download, Pencil, Trash2, Upload } from "lucide-react";
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
    <nav className="sessionList" aria-label="Sessions">
      <div className="sessionListHeader">
        <div className="sessionListTitleRow">
          <p className="sideTitle">Tasks</p>
          {onImportFile && (
            <>
              <button
                type="button"
                className="sessionImportButton"
                title="Import a session backup (.json)"
                aria-label="Import session backup"
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
        <div className="sessionFilterTabs" role="tablist" aria-label="Session filter">
          {(["all", "recent"] as SessionListFilter[]).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              className={filter === value ? "sessionFilterTab active" : "sessionFilterTab"}
              aria-selected={filter === value}
              onClick={() => onFilterChange(value)}
            >
              {value === "all" ? "All" : "Recent"}
            </button>
          ))}
        </div>
        <input
          type="search"
          className="sessionSearchInput"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search tasks…"
          aria-label="Search sessions"
        />
      </div>
      {groups.length === 0 && (
        <p className="sessionListEmpty muted">
          {query.trim()
            ? `No tasks match “${query.trim()}”.`
            : filter === "recent"
              ? "No tasks in the last 7 days."
              : "No tasks yet."}
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
              showLive={active?.session_id === session.session_id && isRunning}
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
  const title = cleanSessionTitle(String(session.title || "Untitled"));
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
        <button className="session sessionFlat" onClick={() => onSelect(session)} title={hint || title}>
          <span className="sessionTitleRow">
            {showLive && <span className="sessionLiveDot" aria-label="Live" />}
            <span className="sessionTitleText">{title}</span>
          </span>
          {preview && !isActive && !compact && <small className="sessionPreview">{preview}</small>}
        </button>
      )}
      <button
        className="sessionRename"
        title="Rename session"
        aria-label="Rename session"
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
        title="Export (backup) session"
        aria-label="Export session backup"
        onClick={(event) => event.stopPropagation()}
      >
        <Download size={13} />
      </a>
      <button
        className="sessionDelete"
        title="Delete session"
        aria-label="Delete session"
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
