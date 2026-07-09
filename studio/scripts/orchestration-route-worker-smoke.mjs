/**
 * Smoke: persistent route worker responds within reasonable latency.
 */
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RuntimeRouteClient } from "../lib/runtime-route-client.mjs";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const python = process.env.ASTERIA_PYTHON || "python";
const moduleName = process.env.ASTERIA_MODULE || "asteria_runtime";

const workspace = await mkdtemp(path.join(os.tmpdir(), "asteria-route-worker-smoke-"));
await initWorkspace(workspace);

const client = new RuntimeRouteClient({ python, runtimeRoot: repoRoot, moduleName });
const started = performance.now();
const first = await client.route({
  root: workspace,
  message: "Python 里 list 和 tuple 有什么区别？",
});
const firstMs = Math.round(performance.now() - started);

const cachedStarted = performance.now();
const second = await client.route({
  root: workspace,
  message: "Python 里 list 和 tuple 有什么区别？",
});
const cachedMs = Math.round(performance.now() - cachedStarted);

assert(first.capability_id === "chat_answer", `expected chat_answer, got ${first.capability_id}`);
assert(
  first.transport === "worker" || first.transport === "subprocess",
  `unexpected transport ${first.transport}`,
);
assert(second.transport === "cache", `expected cache hit, got ${second.transport}`);
assert(firstMs < 5000, `first route too slow: ${firstMs}ms`);
assert(cachedMs < 50, `cache route too slow: ${cachedMs}ms`);

await client.close();
await rm(workspace, { recursive: true, force: true });
console.log(`Route worker smoke passed (first=${firstMs}ms cache=${cachedMs}ms)`);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function initWorkspace(target) {
  const repo = repoRoot.replace(/\\/g, "/");
  const script = `
from pathlib import Path
import sys
root = Path(sys.argv[1])
repo = Path("${repo}")
sys.path.insert(0, str(repo))
from asteria_runtime.commands.init_command import InitCommand
InitCommand(root).run()
`;
  await runCommand([python, "-c", script, target], repoRoot);
}

function runCommand(command, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command[0], command.slice(1), { cwd, env: process.env, windowsHide: true });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("close", (code) =>
      code === 0 ? resolve() : reject(new Error(stderr || `exit ${code}`)),
    );
  });
}
