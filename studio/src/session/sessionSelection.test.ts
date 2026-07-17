import { describe, expect, it } from "vitest";
import { planSessionSelection } from "./sessionSelection";

describe("planSessionSelection", () => {
  it("switching sessions resets the transcript and the evidence selection", () => {
    expect(planSessionSelection("s1", "s2")).toEqual({
      clearEvents: true,
      clearEvidenceSelection: true,
      applyUiState: true,
    });
  });

  it("re-selecting the ACTIVE session keeps the transcript", () => {
    // The regression: clearing here emptied the thread while the id stayed put, so the id-keyed
    // subscription effect never re-ran and the dedup set blocked any refill. Permanent empty state
    // until the user switched away and back — hit on every reload.
    expect(planSessionSelection("s1", "s1").clearEvents).toBe(false);
    expect(planSessionSelection("s1", "s1").clearEvidenceSelection).toBe(false);
  });

  it("ALWAYS restores the saved view, including on the same session", () => {
    // The counter-regression: the same-session early return also skipped applySessionUiState, the
    // only read-back of ui_state (bootstrap auto-selects without coming through here). A saved diff
    // layout was then reachable only by switching away and back.
    expect(planSessionSelection("s1", "s1").applyUiState).toBe(true);
    expect(planSessionSelection("s1", "s2").applyUiState).toBe(true);
    expect(planSessionSelection(null, "s1").applyUiState).toBe(true);
  });

  it("first selection with no active session is a real switch", () => {
    expect(planSessionSelection(null, "s1").clearEvents).toBe(true);
    expect(planSessionSelection(undefined, "s1").clearEvents).toBe(true);
    expect(planSessionSelection("", "s1").clearEvents).toBe(true);
  });
});
