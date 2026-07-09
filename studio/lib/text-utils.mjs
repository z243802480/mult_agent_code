// Redaction + small text/number helpers shared across the Studio server.
// Extracted verbatim from server.mjs (no behavior change) as part of splitting that
// monolith into cohesive modules.

// A key names a credential we must redact. Note the deliberate carve-out: token *count* / usage
// telemetry fields (estimated_input_tokens, context_window_tokens, total_tokens, token_count, …)
// contain the substring "token" but are NOT secrets — redacting them broke the context/token meter.
// We still redact every real credential shape (api_key, authorization, *_token, bearer, secret, …).
export function isSecretKey(key) {
  const k = String(key).toLowerCase();
  if (
    /tokens?$/.test(k) &&
    /(input|output|total|prompt|completion|context|window|estimated|max|min|cache|used|remaining|budget|count|num|per_)/.test(
      k,
    )
  )
    return false;
  if (k === "token_count" || k === "num_tokens" || k === "n_tokens") return false;
  return (
    /api[_-]?key|authorization|secret|password|credential/.test(k) ||
    /(^|[_-])(access|refresh|auth|id|bearer|api|session|csrf|xsrf|private)[_-]?tokens?$/.test(k) ||
    k === "token"
  );
}

export function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== "object")
    return typeof value === "string" ? redactText(value) : value;
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    result[key] = isSecretKey(key) ? "[REDACTED]" : redact(item);
  }
  return result;
}

export function redactText(text) {
  return String(text)
    .replace(
      /(api[_-]?key|authorization|token|secret|password)\s*[:=]\s*['"]?[^'",}\s]+/gi,
      "$1=[REDACTED]",
    )
    .replace(/(bearer\s+)[A-Za-z0-9._-]+/gi, "$1[REDACTED]");
}

export function tailText(text, limit) {
  return text.length > limit ? text.slice(-limit) : text;
}

export function percentile(values, q) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)))];
}
