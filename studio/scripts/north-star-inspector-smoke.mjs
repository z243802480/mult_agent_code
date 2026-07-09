import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-north-star-smoke-"));
const port = 8787 + Math.floor(Math.random() * 200);

await runPython([
  "-m",
  "asteria_runtime",
  "init",
  "--root",
  workspace,
  "--north-star-title",
  "Smoke North Star",
  "--north-star-statement",
  "Inspector read-only long horizon panel",
]);

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port)],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      ASTERIA_STUDIO_CHAT_BACKEND: "local",
    },
  },
);

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => {
  stdout += chunk;
});
server.stderr.on("data", (chunk) => {
  stderr += chunk;
});

try {
  await waitForHealth();
  const diagnostics = await fetchJson("/api/diagnostics");
  const longHorizon = diagnostics.long_horizon ?? {};
  assert(
    longHorizon.north_star_configured === true,
    "diagnostics should report configured north star",
  );
  assert(
    longHorizon.status === "configured",
    `expected configured status, got ${longHorizon.status}`,
  );
  assert(
    longHorizon.north_star?.title === "Smoke North Star",
    "north star title should surface in diagnostics",
  );
  assert(
    typeof longHorizon.north_star?.active_milestone === "string" &&
      longHorizon.north_star.active_milestone.length > 0,
    "active milestone should surface",
  );
  console.log("Studio North Star inspector smoke passed");
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
  throw new Error(
    `Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`,
  );
}

async function fetchJson(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${route}`);
  return response.json();
}

function runPython(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.ASTERIA_PYTHON || "python", args, {
      cwd: repoRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => {
      if (code === 0) resolve(undefined);
      else reject(new Error(`python ${args.join(" ")} failed: ${stderr}`));
    });
  });
}
