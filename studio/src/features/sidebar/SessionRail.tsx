import React from "react";
import type { StudioSession } from "../../types";
import {
  cleanSessionTitle,
  filterSessions,
  sessionInitial,
  sessionPreview,
} from "./sessionListUtils";
import type { SessionListFilter } from "./sessionListUtils";

type SessionRailProps = {
  sessions: StudioSession[];
  active: StudioSession | null;
  isRunning: boolean;
  filter: SessionListFilter;
  onSelect: (session: StudioSession) => void;
};

export function SessionRail({ sessions, active, isRunning, filter, onSelect }: SessionRailProps) {
  const visibleSessions = React.useMemo(() => filterSessions(sessions, filter), [sessions, filter]);

  return (
    <nav className="sessionRailList" aria-label="会话">
      {visibleSessions.map((session) => {
        const isActive = active?.session_id === session.session_id;
        const showLive = isActive && isRunning;
        const title = cleanSessionTitle(String(session.title || "未命名"));
        const preview = sessionPreview(session);
        const hint = [title, preview, new Date(session.updated_at).toLocaleString()]
          .filter(Boolean)
          .join(" · ");
        return (
          <button
            key={session.session_id}
            type="button"
            className={isActive ? "sessionRailItem active" : "sessionRailItem"}
            title={hint}
            aria-label={title}
            onClick={() => onSelect(session)}
          >
            {showLive && <span className="sessionLiveDot sessionLiveDotRail" aria-hidden="true" />}
            <span>{sessionInitial(title)}</span>
          </button>
        );
      })}
    </nav>
  );
}
