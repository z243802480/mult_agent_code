import React from "react";
import type { StudioSession } from "../types";

type StudioKeyboardOptions = {
  sessions: StudioSession[];
  activeSessionId?: string;
  onTogglePanel: () => void;
  onToggleSidebar: () => void;
  onToggleDiffFocus: () => void;
  onToggleSideChat: () => void;
  onSelectSession: (session: StudioSession) => void;
};

export function useStudioKeyboard({
  sessions,
  activeSessionId,
  onTogglePanel,
  onToggleSidebar,
  onToggleDiffFocus,
  onToggleSideChat,
  onSelectSession,
}: StudioKeyboardOptions) {
  React.useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey && event.shiftKey && (event.key === "d" || event.key === "D")) {
        event.preventDefault();
        onToggleDiffFocus();
        return;
      }
      if (event.ctrlKey && (event.key === ";" || event.code === "Semicolon")) {
        event.preventDefault();
        onToggleSideChat();
        return;
      }
      if (event.ctrlKey && event.key === "\\") {
        event.preventDefault();
        onTogglePanel();
        return;
      }
      if (event.ctrlKey && (event.key === "b" || event.key === "B")) {
        event.preventDefault();
        onToggleSidebar();
        return;
      }
      if (!event.ctrlKey || sessions.length < 2) return;
      if (event.key !== "Tab") return;
      event.preventDefault();
      const index = sessions.findIndex((session) => session.session_id === activeSessionId);
      if (index < 0) return;
      const delta = event.shiftKey ? -1 : 1;
      const next = sessions[(index + delta + sessions.length) % sessions.length];
      onSelectSession(next);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [sessions, activeSessionId, onTogglePanel, onToggleSidebar, onToggleDiffFocus, onToggleSideChat, onSelectSession]);
}
