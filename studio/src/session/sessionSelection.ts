/**
 * What re-selecting a session in the sidebar should reset.
 *
 * Extracted as a pure decision because both halves of it were regressions found in production:
 *
 *  - Clearing events on the ALREADY-ACTIVE session wiped the transcript while the id stayed put, so
 *    the subscription effect never re-ran and its dedup set had already marked every event as seen.
 *    The thread stuck on the empty state until the user switched away and back — hit on every
 *    reload, because bootstrap auto-selects the latest session and the first click usually IS it.
 *  - Skipping applySessionUiState on that same path orphaned the only read-back of `ui_state`
 *    (bootstrap auto-selects without going through selectSession), so a saved diff layout/stage/
 *    scope was unreachable except by switching away and back.
 *
 * The two fixes pull in opposite directions on the same branch, which is exactly why the rule is
 * stated once, here, rather than inferred from a control-flow read of the component.
 */
export type SessionSelectionPlan = {
  /** Drop the loaded transcript — only correct when the session actually changed. */
  clearEvents: boolean;
  /** Drop the run-evidence selection — same rule as the transcript. */
  clearEvidenceSelection: boolean;
  /** Restore the session's saved view. Always: this is `ui_state`'s only read-back path. */
  applyUiState: boolean;
};

export function planSessionSelection(
  activeSessionId: string | null | undefined,
  nextSessionId: string,
): SessionSelectionPlan {
  const sameSession = Boolean(activeSessionId) && nextSessionId === activeSessionId;
  return {
    clearEvents: !sameSession,
    clearEvidenceSelection: !sameSession,
    applyUiState: true,
  };
}
