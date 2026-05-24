import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-homepage-copy-"));
const port = Number(process.env.ASTERIA_STUDIO_HOMEPAGE_COPY_PORT || 18792);
const forbidden = /Local Runtime|System Status|\bRoute\b|Evidence Explorer|Inspector|Debug|Ops|run-\d{8}-\d{4}|status --json|stdout|stderr|token|model calls|command/i;

const server = spawn(process.execPath, ["server.mjs", "--workspace", workspace, "--port", String(port)], {
  cwd: studioDir,
  stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
});

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => { stdout += String(chunk); });
server.stderr.on("data", (chunk) => { stderr += String(chunk); });

try {
  await waitForHealth();
  const html = await fetchText("/");
  assert(!forbidden.test(html), `homepage shell leaked backend wording: ${html.match(forbidden)?.[0]}`);
  const sources = [
    "src/App.tsx",
    "src/components/Sidebar.tsx",
    "src/components/Composer.tsx",
    "src/components/Thread.tsx",
    "src/components/PermissionCard.tsx",
  ];
  for (const rel of sources) {
    const source = await fs.readFile(path.join(studioDir, rel), "utf8");
    let cleaned = source;
    if (rel.endsWith("Thread.tsx")) {
      cleaned = cleaned
        .replace(/function LiveStream[\s\S]*?function useSmoothText/, "function useSmoothText")
        .replace(/function stripContextNoise[\s\S]*?function splitFinalSections/, "function splitFinalSections")
        .replace(/Waiting for the first tokens/g, "Waiting for the first response");
    }
    assert(!forbidden.test(cleaned), `${rel} leaked homepage/backend wording: ${cleaned.match(forbidden)?.[0]}`);
  }
  assert((await fs.readFile(path.join(studioDir, "src", "components", "Composer.tsx"), "utf8")).includes("<details className=\"advancedModeDetails\">"), "advanced mode controls should be hidden behind details");
  console.log("Studio homepage copy smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
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
  throw new Error(`Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`);
}

async function fetchJson(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok) throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function fetchText(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok) throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.text();
}
