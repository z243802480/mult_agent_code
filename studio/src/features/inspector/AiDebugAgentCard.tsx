import React, { useState } from "react";
import { Bug, SendHorizontal } from "lucide-react";
import type { RunDetailPayload } from "../../types";
import { firstText } from "../../narrative";
import { asRecord, latestRoute, runtimeProgressFromDetail } from "./inspectorUtils";

export function AiDebugAgentCard({
  runDetail,
  selectedRunId,
}: {
  runDetail: RunDetailPayload | null;
  selectedRunId: string | null;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const latestRunId = selectedRunId || String(runDetail?.run_id ?? "");
  return (
    <section className="debugAgentCard">
      <div className="debugAgentHeader">
        <span className="debugAgentIcon">
          <Bug size={15} />
        </span>
        <div>
          <h2>运行诊断</h2>
          <p>
            查阅已记录的运行证据 —
            阻塞项、模型路由、下一步动作、开销、门禁、策略。这是对所选运行的确定性读取,不经过模型。
          </p>
        </div>
      </div>
      <div className="debugAgentHints">
        <button type="button" onClick={() => setQuestion("Why is the latest run blocked?")}>
          为何被阻塞?
        </button>
        <button
          type="button"
          onClick={() => setQuestion("Why did Asteria choose this model route?")}
        >
          模型路由?
        </button>
        <button
          type="button"
          onClick={() => setQuestion("What backend action should I take next?")}
        >
          下一步动作?
        </button>
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
          placeholder="提一个运维问题,例如:这次运行为何被阻塞?"
          rows={2}
        />
        <button type="submit" title="查阅运行诊断">
          <SendHorizontal size={14} />
        </button>
      </form>
      {answer ? (
        <pre className="debugAgentAnswer">{answer}</pre>
      ) : (
        <p className="debugAgentNote">
          只读回答基于所选运行的上下文{latestRunId ? ` (${latestRunId})` : ""}
          ;不会执行命令或修改文件。
        </p>
      )}
    </section>
  );
}

function debugAnswerFor(
  question: string,
  runDetail: RunDetailPayload | null,
  runId: string,
): string {
  const lower = question.toLowerCase();
  const progress = runtimeProgressFromDetail(runDetail);
  const loop = asRecord(progress.loop);
  const blocker = firstText(
    progress.current_blocker,
    loop.current_blocker,
    runDetail?.run_loop_summary?.current_blocker,
    "未记录阻塞项。",
  );
  const next = firstText(
    progress.next_command,
    runDetail?.main_action?.next_command,
    "未记录下一步动作。",
  );
  const route = latestRoute(runDetail);
  const routeLine = route
    ? `${firstText(route.purpose, "task")} -> ${firstText(route.selected_tier, route.tier, "unknown")}: ${firstText(route.reason, route.model_selection_reason, "未记录路由原因。")}`
    : "本次运行未记录模型路由证据。";
  if (lower.includes("route") || lower.includes("model")) {
    return [`运行: ${runId || "latest"}`, "模型路由:", routeLine].join("\n");
  }
  if (lower.includes("next") || lower.includes("action")) {
    return [
      `运行: ${runId || "latest"}`,
      `建议的下一步动作: ${next}`,
      `当前阻塞项: ${blocker}`,
    ].join("\n");
  }
  return [
    `运行: ${runId || "latest"}`,
    `当前阻塞项: ${blocker}`,
    `建议的下一步动作: ${next}`,
    `路由: ${routeLine}`,
  ].join("\n");
}
