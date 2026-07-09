// Pure path / id safety predicates for the Studio server, extracted verbatim from server.mjs.
// `isSafeWorkspacePath` is the protected-path guard (denies .git/secrets/.env/keys/id_rsa/
// node_modules/dist and any parent-traversal) — it is the single source of truth for "may the
// UI touch this workspace-relative path" and is imported by the git helpers too.
import path from "node:path";

export function isSafeId(value) {
  return /^[A-Za-z0-9_.-]+$/.test(String(value || ""));
}

export function isSafeWorkspacePath(relative) {
  const normalized = String(relative || "").replace(/\\/g, "/");
  if (!normalized || normalized.includes("..")) return false;
  if (/^\.git(\/|$)/i.test(normalized) || /^secrets(\/|$)/i.test(normalized)) return false;
  if (/\.env(\.|$)/i.test(path.basename(normalized))) return false;
  if (/\.(pem|key)$/i.test(normalized)) return false;
  if (/(^|\/)(id_rsa|id_ed25519|model\.routes\.local\.(ps1|json))$/i.test(normalized)) return false;
  if (/(node_modules|dist)(\/|$)/i.test(normalized)) return false;
  return true;
}

export function isPreviewableFile(relative) {
  return /\.(md|txt|json|jsonl|py|ts|tsx|js|mjs|css|html|toml|yaml|yml)$/i.test(relative);
}

export function workspaceBasename(value) {
  const normalized = String(value || "").replace(/[\\/]+$/, "");
  return path.basename(normalized) || normalized || "workspace";
}

export function isAbsoluteWorkspacePath(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  return path.isAbsolute(text);
}
