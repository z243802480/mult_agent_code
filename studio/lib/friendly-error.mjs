// User-facing error/runtime-text helpers for the Studio server, extracted verbatim from
// server.mjs. Pure string transformers (input text → friendly markdown / category / summary);
// the only dependency is `redactText` from ./text-utils.mjs.
import { redactText } from "./text-utils.mjs";

export function friendlyErrorText(text) {
  const raw = String(text || "");
  const lower = raw.toLowerCase();
  if (/ssl|_ssl|handshake|urlopen|tls/.test(lower) && /timed out|timeout/.test(lower)) {
    return [
      "## Connection timed out",
      "The model service did not finish the HTTPS security handshake in time. This is usually caused by network, proxy/VPN, firewall, or a temporarily slow provider, not by your prompt.",
      "",
      "## What you can do",
      "- Retry once.",
      "- If it keeps happening, check your proxy/VPN and network stability.",
      "- Try again later, or switch to another available model route.",
    ].join("\n");
  }
  if (/timed out|timeout|deadline/.test(lower)) {
    return [
      "## Request timed out",
      "This request waited too long. The network or model service may be temporarily unstable.",
      "",
      "## What you can do",
      "- Retry once.",
      "- Shorten the request or reduce the task scope.",
      "- If it keeps failing, try again later or switch models.",
    ].join("\n");
  }
  if (
    /\b(401|403|unauthorized|forbidden|invalid[_ ]?api[_ ]?key|authentication failed)\b/.test(lower)
  ) {
    return [
      "## Authentication failed",
      "The model provider rejected the credentials (401/403) — the API key is likely missing, wrong, or lacks access to this model.",
      "",
      "## What you can do",
      "- Check the provider API key environment variable is set correctly.",
      "- Run `asteria model-check` to verify the configured provider.",
    ].join("\n");
  }
  if (/\b(429|rate limit|quota|insufficient_quota|too many requests)\b/.test(lower)) {
    return [
      "## Rate limited or quota exhausted",
      "The provider is throttling requests or the account quota is used up (429).",
      "",
      "## What you can do",
      "- Wait a moment and retry.",
      "- Check billing/quota, or switch to another model route.",
    ].join("\n");
  }
  if (
    /model[^\n]*(not found|does not exist|unknown|not available)|no such model|invalid model|model_not_found/.test(
      lower,
    )
  ) {
    return [
      "## Model not available",
      "The requested model name was not found by the provider.",
      "",
      "## What you can do",
      "- Check the model name configured for this tier.",
      "- Run `asteria model-check` to confirm the route.",
    ].join("\n");
  }
  if (
    /econnrefused|connection refused|failed to connect|getaddrinfo|enotfound|network is unreachable|proxy/.test(
      lower,
    )
  ) {
    return [
      "## Cannot reach the model service",
      "The service address could not be reached (connection refused / DNS). The base URL, port, proxy, or a local model server may be down.",
      "",
      "## What you can do",
      "- Check the provider base URL and that any local model server is running.",
      "- Check proxy/VPN settings, then retry.",
    ].join("\n");
  }
  // Unknown shape: never go blank (which read as a vague "could not be completed"). Surface the first
  // meaningful, redacted line of the REAL error so the user sees WHAT failed, plus generic next steps.
  const firstLine = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !/^(traceback|file ")/i.test(line) && !/^\s*at\s/i.test(line));
  if (!firstLine) return "";
  return [
    "## The task hit an error",
    redactText(firstLine).slice(0, 300),
    "",
    "## What you can do",
    "- Retry the step.",
    "- Open the Inspector for the full diagnostics.",
    "- If it repeats, reduce the scope or switch the model route.",
  ].join("\n");
}

// Coarse error category for UI badging (auth/rate_limit/timeout/network/model/unknown). Honest: only
// returns a category actually detected in the text; never invents a code.
export function friendlyErrorCategory(text) {
  const lower = String(text || "").toLowerCase();
  if (
    /\b(401|403|unauthorized|forbidden|invalid[_ ]?api[_ ]?key|authentication failed)\b/.test(lower)
  )
    return "auth";
  if (/\b(429|rate limit|quota|insufficient_quota|too many requests)\b/.test(lower))
    return "rate_limit";
  if (/timed out|timeout|deadline|handshake/.test(lower)) return "timeout";
  if (
    /econnrefused|connection refused|failed to connect|getaddrinfo|enotfound|network is unreachable|proxy|ssl|tls/.test(
      lower,
    )
  )
    return "network";
  if (
    /model[^\n]*(not found|does not exist|unknown|not available)|no such model|invalid model|model_not_found/.test(
      lower,
    )
  )
    return "model";
  return "unknown";
}

export function friendlyErrorTitle(text) {
  const friendly = friendlyErrorText(text);
  if (!friendly) return "";
  const heading = friendly.split("\n").find((line) => line.startsWith("## "));
  return heading ? heading.slice(3).trim() : "";
}

export function friendlyErrorSummary(text) {
  const friendly = friendlyErrorText(text);
  if (!friendly) return "";
  return (
    friendly.split("\n").find((line) => line && !line.startsWith("##")) ||
    "The request could not be completed."
  );
}

export function summarizeRuntimeChunk(text) {
  const clean = String(text || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return "后台有新的运行输出。";
  if (/timeout|deadline|timed out/i.test(clean)) return "模型或运行步骤出现超时迹象。";
  if (/error|failed|traceback/i.test(clean)) return "运行过程中出现错误，需要核对。";
  if (/plan|goal|task/i.test(clean)) return "runtime 正在返回任务相关内容。";
  if (/created|written|file/i.test(clean)) return "运行过程产生了文件或产物更新。";
  return clean.slice(0, 120);
}
