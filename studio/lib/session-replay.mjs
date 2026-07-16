// G15 会话回放导出 — a SELF-CONTAINED HTML replay page for one session (OpenCode share / Manus
// replay, minus the cloud: this is a file you forward on the intranet, not a hosted link).
//
// Design constraints:
//   - Zero dependencies at view time: inline CSS + inline vanilla JS, no external requests at all.
//   - The transcript is embedded as JSON and rendered client-side, so the page stays small and the
//     raw data stays inspectable (the JSON bundle export remains the lossless backup format).
//   - Everything user-controlled is HTML-escaped — a shared file must never execute transcript
//     content, and the embedded JSON escapes `<` so `</script>` inside a message cannot break out.
//   - Honest scope: the replay shows MAIN-thread events (what the user saw in the thread). The
//     page says so and points at the JSON export for the full raw evidence.

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Events worth replaying: the main-thread view, minus token-stream deltas (finals carry the text). */
export function replayEvents(events) {
  return (Array.isArray(events) ? events : []).filter((event) => {
    if (!event || typeof event !== "object") return false;
    if (event.display_level && event.display_level !== "main") return false;
    const type = String(event.type ?? "");
    if (type === "model_delta" || type === "reasoning_delta" || type === "assistant_delta")
      return false;
    return true;
  });
}

export function renderSessionReplayHtml(session, events) {
  const title = String(session?.title ?? "Asteria 会话");
  const kept = replayEvents(events).map((event) => ({
    type: String(event.type ?? ""),
    status: String(event.status ?? ""),
    title: String(event.title ?? ""),
    summary: String(event.summary ?? ""),
    content_delta: String(event.content_delta ?? ""),
    created_at: String(event.created_at ?? ""),
    command: Array.isArray(event.command) ? event.command.map(String) : undefined,
  }));
  // `<` must not survive inside the JSON script block ("</script>" in a transcript would end the
  // block and turn the rest of the message into live markup).
  const payload = JSON.stringify({
    session: {
      session_id: String(session?.session_id ?? ""),
      title,
      workspace: String(session?.workspace ?? ""),
      created_at: String(session?.created_at ?? ""),
      updated_at: String(session?.updated_at ?? ""),
    },
    events: kept,
  }).replaceAll("<", "\\u003c");

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} · Asteria 会话回放</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0 auto; max-width: 760px; padding: 24px 16px 64px; font: 15px/1.7 system-ui, "Segoe UI", sans-serif; color: #24292f; background: #ffffff; }
  @media (prefers-color-scheme: dark) { body { color: #d0d7de; background: #0d1117; } .user { background: #1c2430 !important; } details { border-color: #30363d !important; } .final { border-color: #30363d !important; } }
  header { border-bottom: 1px solid #d0d7de55; margin-bottom: 20px; padding-bottom: 10px; }
  header h1 { font-size: 18px; margin: 0 0 4px; }
  header p { color: #6e7781; font-size: 12.5px; margin: 0; }
  .user { background: #f0f4f8; border-radius: 10px; margin: 22px 0 10px; padding: 10px 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .final { border-left: 3px solid #6e7781aa; margin: 10px 0; padding: 2px 0 2px 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .final.failed { border-left-color: #cf222e; }
  details { border: 1px solid #d0d7de77; border-radius: 8px; margin: 8px 0; }
  summary { color: #6e7781; cursor: pointer; font-size: 12.5px; padding: 6px 10px; }
  .step { border-top: 1px solid #d0d7de44; font-size: 12.5px; padding: 5px 10px; overflow-wrap: anywhere; }
  .step .cmd { font-family: ui-monospace, monospace; font-size: 12px; }
  .step.failed { color: #cf222e; }
  footer { color: #6e7781; font-size: 11.5px; margin-top: 40px; }
</style>
</head>
<body>
<header>
  <h1>${escapeHtml(title)}</h1>
  <p id="meta"></p>
</header>
<main id="thread"></main>
<footer>此页只包含主线程转录（用户所见的对话与过程摘要）；完整原始证据在会话的 JSON 备份导出里。由 Asteria Studio 生成，可离线打开。</footer>
<script type="application/json" id="replay-data">${payload}</script>
<script>
(function () {
  var data = JSON.parse(document.getElementById("replay-data").textContent);
  var meta = document.getElementById("meta");
  meta.textContent = (data.session.workspace ? data.session.workspace + " · " : "") +
    (data.session.created_at || "") + (data.session.updated_at ? " → " + data.session.updated_at : "");
  var thread = document.getElementById("thread");
  var pendingSteps = [];
  function flushSteps() {
    if (!pendingSteps.length) return;
    var details = document.createElement("details");
    var summary = document.createElement("summary");
    summary.textContent = "过程 · " + pendingSteps.length + " 步";
    details.appendChild(summary);
    pendingSteps.forEach(function (step) {
      var div = document.createElement("div");
      div.className = "step" + (step.status === "failed" ? " failed" : "");
      var label = step.title || step.type;
      if (step.command && step.command.length) {
        var cmd = document.createElement("span");
        cmd.className = "cmd";
        cmd.textContent = "$ " + step.command.join(" ");
        div.textContent = "";
        div.appendChild(cmd);
      } else {
        div.textContent = label + (step.summary ? " — " + step.summary : "");
      }
      details.appendChild(div);
    });
    thread.appendChild(details);
    pendingSteps = [];
  }
  data.events.forEach(function (event) {
    if (event.type === "user_message") {
      flushSteps();
      var user = document.createElement("div");
      user.className = "user";
      user.textContent = event.content_delta || event.summary || event.title;
      thread.appendChild(user);
      return;
    }
    if (event.type === "final_answer" || event.type === "error") {
      var text = event.content_delta || event.summary;
      if (!text) return;
      flushSteps();
      var final = document.createElement("div");
      final.className = "final" + (event.type === "error" ? " failed" : "");
      final.textContent = text;
      thread.appendChild(final);
      return;
    }
    pendingSteps.push(event);
  });
  flushSteps();
})();
</script>
</body>
</html>
`;
}
