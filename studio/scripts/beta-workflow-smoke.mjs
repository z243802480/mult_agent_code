import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-beta-workflow-smoke-"));
const port = 8787 + Math.floor(Math.random() * 200);

await runPython(["-m", "asteria_runtime", "init", "--root", workspace]);

const server = spawn(process.execPath, ["server.mjs", "--workspace", workspace, "--port", String(port)], {
  cwd: studioDir,
  stdio: ["ignore", "pipe", "pipe"],
  env: {
    ...process.env,
    ASTERIA_STUDIO_CHAT_BACKEND: "local",
  },
});

let stdout = "";
server.stdout.on("data", (chunk) => { stdout += chunk; });
server.stderr.on("data", (chunk) => { stdout += chunk; });

await waitFor(() => stdout.includes("Asteria Studio listening"), 15000, "studio server did not start");

try {
  const health = await fetchJson(`http://127.0.0.1:${port}/api/health`);
  assert(health.ok === true, "health endpoint should be ok");

  const diagnostics = await fetchJson(`http://127.0.0.1:${port}/api/diagnostics`);
  assert(diagnostics.diagnostics_loaded === true, "diagnostics should be loaded");
  assert(typeof diagnostics.workflow === "object" && diagnostics.workflow !== null, "workflow object required");
  for (const key of ["can_review", "can_accept", "workflow_state", "recommended_next_command"]) {
    assert(key in diagnostics.workflow, `workflow.${key} should be present`);
  }
  console.log("beta-workflow-smoke: ok");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => server.on("close", resolve));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  return response.json();
}

async function waitFor(predicate, timeoutMs, message) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(message);
}

function runPython(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.ASTERIA_PYTHON || "python", args, {
      cwd: path.resolve(studioDir, ".."),
      stdio: "inherit",
      env: {
        ...process.env,
        PYTHONPATH: path.resolve(studioDir, "..", "src"),
      },
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`python exited with ${code}`));
    });
  });
}
