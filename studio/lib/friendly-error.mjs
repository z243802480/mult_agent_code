// User-facing error/runtime-text helpers for the Studio server, extracted verbatim from
// server.mjs. Pure string transformers (input text → friendly markdown / category / summary);
// the only dependency is `redactText` from ./text-utils.mjs.
//
// Chinese on the main thread (R2-15, same discipline as F4/R2-1): these cards render in the
// conversation next to Chinese guidance from the runtime — an English shell around a Chinese
// refusal read as two conflicting instructions. Detection stays on the English/technical error
// text; only the rendered words are localized. `friendlyErrorCategory` still classifies for UI
// badging and is untouched.
import { redactText } from "./text-utils.mjs";

export function friendlyErrorText(text) {
  const raw = String(text || "");
  const lower = raw.toLowerCase();
  if (/ssl|_ssl|handshake|urlopen|tls/.test(lower) && /timed out|timeout/.test(lower)) {
    return [
      "## 连接超时",
      "模型服务没有在时限内完成 HTTPS 安全握手。通常是网络、代理/VPN、防火墙或服务商临时变慢，与你的提示内容无关。",
      "",
      "## 可以这样做",
      "- 先重试一次。",
      "- 反复出现时，检查代理/VPN 和网络稳定性。",
      "- 也可以稍后再试，或换一条可用的模型路线。",
    ].join("\n");
  }
  if (/timed out|timeout|deadline/.test(lower)) {
    return [
      "## 请求超时",
      "这次请求等得太久。网络或模型服务可能临时不稳定。",
      "",
      "## 可以这样做",
      "- 先重试一次。",
      "- 缩短请求或缩小任务范围。",
      "- 反复失败时，稍后再试或换一个模型。",
    ].join("\n");
  }
  if (
    /\b(401|403|unauthorized|forbidden|invalid[_ ]?api[_ ]?key|authentication failed)\b/.test(lower)
  ) {
    return [
      "## 鉴权失败",
      "模型服务商拒绝了凭证（401/403）——API key 很可能缺失、填错，或没有这个模型的权限。",
      "",
      "## 可以这样做",
      "- 检查服务商 API key 环境变量是否设置正确。",
      "- 运行 `asteria model-check` 核对配置的服务商。",
    ].join("\n");
  }
  if (/\b(429|rate limit|quota|insufficient_quota|too many requests)\b/.test(lower)) {
    return [
      "## 触发限流或额度用尽",
      "服务商正在限流，或账户额度已用完（429）。",
      "",
      "## 可以这样做",
      "- 稍等片刻再重试。",
      "- 检查账单/额度，或换一条模型路线。",
    ].join("\n");
  }
  if (
    /model[^\n]*(not found|does not exist|unknown|not available)|no such model|invalid model|model_not_found/.test(
      lower,
    )
  ) {
    return [
      "## 模型不可用",
      "服务商找不到请求的模型名。",
      "",
      "## 可以这样做",
      "- 检查该档位配置的模型名。",
      "- 运行 `asteria model-check` 确认路线。",
    ].join("\n");
  }
  if (
    /econnrefused|connection refused|failed to connect|getaddrinfo|enotfound|network is unreachable|proxy/.test(
      lower,
    )
  ) {
    return [
      "## 连不上模型服务",
      "服务地址无法访问（连接被拒 / DNS 解析失败）。base URL、端口、代理或本地模型服务可能没起来。",
      "",
      "## 可以这样做",
      "- 检查服务商 base URL 和本地模型服务是否在运行。",
      "- 检查代理/VPN 设置后重试。",
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
    "## 这一步出了错",
    redactText(firstLine).slice(0, 300),
    "",
    "## 可以这样做",
    "- 重试这一步。",
    "- 打开「证据」面板查看完整诊断。",
    "- 反复出现时，缩小任务范围或换一条模型路线。",
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
    "这次请求没有完成。"
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
