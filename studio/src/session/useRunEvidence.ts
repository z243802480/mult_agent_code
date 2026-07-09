import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import type { OverviewPayload, RunDetailPayload, StudioEvent } from "../types";
import { api } from "../api";
import { pickRunTriggerEvent } from "./eventUtils";

export function useRunEvidence(events: StudioEvent[], onGitRefresh?: () => void) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetailPayload | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<StudioEvent | null>(null);
  const refreshedRunEventRef = useRef("");
  const onGitRefreshRef = useRef(onGitRefresh);
  onGitRefreshRef.current = onGitRefresh;

  const openRun = useCallback(async (runId: string) => {
    if (!runId) return;
    setSelectedRunId(runId);
    setRunDetail(await api.runDetail(runId));
  }, []);

  const openLatestRun = useCallback(
    async (overviewData: OverviewPayload | null) => {
      const latestRunId = String(overviewData?.runs?.[0]?.run_id ?? "");
      if (!latestRunId) {
        setSelectedRunId(null);
        setRunDetail(null);
        return;
      }
      await openRun(latestRunId);
    },
    [openRun],
  );

  // runDetail must track the run awaiting the user (pending decision) over the latest tool run — see
  // pickRunTriggerEvent for the M7 (decision before any tool) / L9 (stale-run mismatch) rationale.
  const runTrigger = useMemo(() => pickRunTriggerEvent(events), [events]);

  useEffect(() => {
    const runId = String(runTrigger?.run_id ?? "");
    const eventId = String(runTrigger?.event_id ?? "");
    if (!runId || !eventId || eventId === refreshedRunEventRef.current) return;
    refreshedRunEventRef.current = eventId;
    void openRun(runId);
    onGitRefreshRef.current?.();
  }, [runTrigger?.event_id, runTrigger?.run_id, openRun]);

  function selectEvent(event: StudioEvent) {
    setSelectedEvent(event);
    if (event.run_id && event.run_id !== selectedRunId) {
      void openRun(event.run_id);
    }
  }

  function selectRunEvidenceEvent(event: StudioEvent) {
    setSelectedEvent(event);
    const runId = String(event.run_id ?? "");
    if (runId && runId !== selectedRunId) {
      void openRun(runId);
    }
  }

  function clearSelection() {
    // Clear the whole run selection, not just the highlighted event: on a session
    // switch a stale runDetail/selectedRunId would keep driving the Thread's
    // runtimeEvents fallback, so the previous session's content would persist.
    setSelectedEvent(null);
    setSelectedRunId(null);
    setRunDetail(null);
    // Let the auto-open effect re-open the new session's latest run (it short-circuits
    // on the last-opened event id, which must be forgotten across a session switch).
    refreshedRunEventRef.current = "";
  }

  return {
    selectedRunId,
    runDetail,
    setRunDetail,
    openRun,
    openLatestRun,
    selectedEvent,
    setSelectedEvent,
    selectEvent,
    selectRunEvidenceEvent,
    clearSelection,
  };
}
