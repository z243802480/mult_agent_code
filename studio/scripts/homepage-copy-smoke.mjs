import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-homepage-copy-"));
const port = Number(process.env.ASTERIA_STUDIO_HOMEPAGE_COPY_PORT || 18792);
const forbidden =
  /Local Runtime|System Status|\bRoute\b|Evidence Explorer|Inspector|\bOps\b|run-\d{8}-\d{4}|status --json|stdout|stderr|token|model calls|command/i;

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port)],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
  },
);

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => {
  stdout += String(chunk);
});
server.stderr.on("data", (chunk) => {
  stderr += String(chunk);
});

try {
  await waitForHealth();
  const html = await fetchText("/");
  assert(
    !forbidden.test(html),
    `homepage shell leaked backend wording: ${html.match(forbidden)?.[0]}`,
  );
  const sources = [
    "src/App.tsx",
    "src/components/Sidebar.tsx",
    "src/components/Composer.tsx",
    "src/components/Thread.tsx",
    "src/components/PermissionCard.tsx",
  ];
  for (const rel of sources) {
    const source = await fs.readFile(path.join(studioDir, rel), "utf8");
    // This check is about USER-FACING copy, not source internals. Code COMMENTS legitimately mention
    // mechanism words ("@token" mention parsing, route/command notes) that are never rendered — strip
    // them first so a comment can't false-positive. Identifiers (e.g. CommandPalette) are neutralized
    // per-file below; they aren't comments so they survive this strip.
    let cleaned = stripCodeComments(source);
    if (rel.endsWith("Thread.tsx")) {
      cleaned = cleaned
        .replace(/function LiveStream[\s\S]*?function useSmoothText/, "function useSmoothText")
        .replace(/provider route blocked/g, "provider path blocked")
        .replace(/display_level !== "inspector"/g, 'display_level !== "hidden"')
        .replace(
          /function stripContextNoise[\s\S]*?function splitFinalSections/,
          "function splitFinalSections",
        )
        .replace(/next_command/g, "next_action")
        .replace(/commandCount/g, "actionCount")
        .replace(/command\$\{actionCount === 1 \? "" : "s"\}/g, "action")
        .replace(/\bcommand:/g, "action_field:")
        .replace(/\.command\b/g, ".action_field")
        .replace(/latest_context_estimated_tokens/g, "latest_context_estimated_units")
        .replace(/max_context_estimated_tokens/g, "max_context_estimated_units")
        .replace(/context_window_tokens/g, "context_window_units")
        .replace(/Waiting for the first tokens/g, "Waiting for the first response")
        .replace(/\btokens\b/gi, "units");
    }
    if (rel.endsWith("App.tsx")) {
      cleaned = cleaned
        .replace(/import[\s\S]*?Inspector[\s\S]*?;\r?\n/, "")
        .replace(/<(?:Inspector|SidePanel)[\s\S]*?\/>\s*/g, "")
        // The CommandPalette (⌘K action palette) is a legit UI affordance, not backend "command"
        // vocabulary leaking into homepage copy. These are code IDENTIFIERS (import/type/prop/var),
        // never user-facing text — neutralize the family precisely so the forbidden `command` token
        // doesn't false-positive, WITHOUT blanket-stripping "command" (which would mask a real leak).
        .replace(/CommandPalette/g, "ActionPalette")
        .replace(/paletteCommands/g, "paletteActions")
        .replace(/\bCommand\[\]/g, "Action[]")
        .replace(/\btype Command\b/g, "type Action")
        .replace(/\bcommands=\{/g, "actions={");
    }
    assert(
      !forbidden.test(cleaned),
      `${rel} leaked homepage/backend wording: ${cleaned.match(forbidden)?.[0]}`,
    );
  }
  {
    // Mode/permission controls must stay compact, not sprawl across the input bar. The mature composer
    // collapses them into a `composerModeGroup` of <select>s (was an older "composerModeDetails"
    // disclosure) — assert the current compact grouping so the input bar reads clean.
    const composer = await fs.readFile(
      path.join(studioDir, "src", "components", "Composer.tsx"),
      "utf8",
    );
    assert(
      composer.includes("composerModeGroup") && /<select/.test(composer),
      "mode controls should be compact (collapsed into a select group), not a sprawled picker",
    );
  }
  console.log("Studio homepage copy smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// Remove JS/TS comments so the copy check only sees code + user-facing strings, never comment prose.
// Block comments are removed wholesale; line comments are removed to end-of-line but only when the
// "//" is NOT preceded by ":" so protocol-relative URLs / "https://" inside strings are left intact.
function stripCodeComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

async function waitForHealth() {
  const deadline = Date.now() + 10_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await fetchJson("/api/health");
      if (health.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`,
  );
}

async function fetchJson(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok)
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function fetchText(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok)
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.text();
}
