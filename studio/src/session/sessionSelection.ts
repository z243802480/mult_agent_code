/**
 * Whether re-selecting a session in the sidebar should reset the loaded transcript and the
 * run-evidence selection.
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
 * stated once, here, rather than inferred from a control-flow read of the component. Restoring the
 * saved view is NOT part of this decision — it is unconditional, so the caller just always does it.
 */
export function shouldResetForSession(
  activeSessionId: string | null | undefined,
  nextSessionId: string,
): boolean {
  return !(Boolean(activeSessionId) && nextSessionId === activeSessionId);
}
