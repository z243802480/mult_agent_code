import React, { useState } from "react";
import { Bug, SendHorizontal } from "lucide-react";
import type { RunDetailPayload } from "../../types";
import { firstText } from "../../narrative";
import { asRecord, latestRoute, runtimeProgressFromDetail } from "./inspectorUtils";

export function AiDebugAgentCard({ runDetail, selectedRunId }: { runDetail: RunDetailPayload | null; selectedRunId: string | null }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const latestRunId = selectedRunId || String(runDetail?.run_id ?? "");
  return (
    <section className="debugAgentCard">
      <div className="debugAgentHeader">
        <span className="debugAgentIcon"><Bug size={15} /></span>
        <div>
          <h2>AI Debug Agent</h2>
          <p>Ask backend questions about runs, blockers, evidence, model routes, costs, gates, and policies.</p>
        </div>
      </div>
      <div className="debugAgentHints">
        <button type="button" onClick={() => setQuestion("Why is the latest run blocked?")}>Why blocked?</button>
        <button type="button" onClick={() => setQuestion("Why did Asteria choose this model route?")}>Model route?</button>
        <button type="button" onClick={() => setQuestion("What backend action should I take next?")}>Next action?</button>
      </div>
      <form
        className="debugAgentComposer"
        onSubmit={(event) => {
          event.preventDefault();
          if (!question.trim()) return;
          setAnswer(debugAnswerFor(question, runDetail, latestRunId));
          setQuestion("");
        }}
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask an Ops question, e.g. why is this run blocked?"
          rows={2}
        />
        <button type="submit" title="Ask Debug Agent">
          <SendHorizontal size={14} />
        </button>
      </form>
      {answer ? <pre className="debugAgentAnswer">{answer}</pre> : (
        <p className="debugAgentNote">
          Read-only answers use the selected run context{latestRunId ? ` (${latestRunId})` : ""}; they do not execute commands or modify files.
        </p>
      )}
    </section>
  );
}

function debugAnswerFor(question: string, runDetail: RunDetailPayload | null, runId: string): string {
  const lower = question.toLowerCase();
  const progress = runtimeProgressFromDetail(runDetail);
  const loop = asRecord(progress.loop);
  const blocker = firstText(progress.current_blocker, loop.current_blocker, runDetail?.run_loop_summary?.current_blocker, "No blocker is recorded.");
  const next = firstText(progress.next_command, runDetail?.main_action?.next_command, "No next action is recorded.");
  const route = latestRoute(runDetail);
  const routeLine = route
    ? `${firstText(route.purpose, "task")} -> ${firstText(route.selected_tier, route.tier, "unknown")}: ${firstText(route.reason, route.model_selection_reason, "No route reason recorded.")}`
    : "No model route evidence is recorded for this run.";
  if (lower.includes("route") || lower.includes("model")) {
    return [`Run: ${runId || "latest"}`, "Model route:", routeLine].join("\n");
  }
  if (lower.includes("next") || lower.includes("action")) {
    return [`Run: ${runId || "latest"}`, `Recommended next action: ${next}`, `Current blocker: ${blocker}`].join("\n");
  }
  return [`Run: ${runId || "latest"}`, `Current blocker: ${blocker}`, `Recommended next action: ${next}`, `Route: ${routeLine}`].join("\n");
}

