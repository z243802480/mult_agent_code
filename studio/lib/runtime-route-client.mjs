/**
 * Persistent Python route worker + TTL cache for Studio orchestration routing.
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import readline from "node:readline";

const DEFAULT_CACHE_TTL_MS = 15_000;
const WORKER_REQUEST_TIMEOUT_MS = 30_000;

export class RuntimeRouteClient {
  #python;
  #runtimeRoot;
  #moduleName;
  #child = null;
  #pending = new Map();
  #nextId = 1;
  #cache = new Map();
  #cacheTtlMs;

  constructor({ python, runtimeRoot, moduleName, cacheTtlMs = DEFAULT_CACHE_TTL_MS }) {
    this.#python = python;
    this.#runtimeRoot = runtimeRoot;
    this.#moduleName = moduleName;
    this.#cacheTtlMs = cacheTtlMs;
  }

  async route({ root, message, requestedMode = "auto", rulesOnly = false, routerMode = null }) {
    const workspace = path.resolve(root);
    const fingerprint = workspaceRouteFingerprint(workspace);
    const cacheKey = buildCacheKey({
      workspace,
      message,
      requestedMode,
      rulesOnly,
      routerMode,
      fingerprint,
    });
    const cached = this.#readCache(cacheKey);
    if (cached) {
      return { ...cached, transport: "cache" };
    }

    const payload = {
      id: `route-${this.#nextId++}`,
      op: "route",
      root: workspace,
      message: String(message || ""),
      mode: requestedMode,
      rules_only: rulesOnly,
      router_mode: routerMode,
      include_catalog: false,
    };

    let response;
    try {
      response = await this.#request(payload);
    } catch (error) {
      response = await this.#fallbackSubprocess(payload, error);
    }

    if (response?.ok !== false && response?.studio_mode) {
      this.#writeCache(cacheKey, response);
    }
    return response;
  }

  invalidateWorkspace(root) {
    const prefix = `${path.resolve(root)}|`;
    for (const key of this.#cache.keys()) {
      if (key.startsWith(prefix)) this.#cache.delete(key);
    }
  }

  async close() {
    if (!this.#child) return;
    this.#child.kill();
    this.#child = null;
    this.#pending.clear();
  }

  reconfigure({ runtimeRoot }) {
    const nextRoot = path.resolve(runtimeRoot);
    if (nextRoot !== this.#runtimeRoot) {
      this.#runtimeRoot = nextRoot;
      void this.close();
    }
  }

  #readCache(cacheKey) {
    const entry = this.#cache.get(cacheKey);
    if (!entry) return null;
    if (Date.now() - entry.stored_at_ms > this.#cacheTtlMs) {
      this.#cache.delete(cacheKey);
      return null;
    }
    return entry.payload;
  }

  #writeCache(cacheKey, payload) {
    this.#cache.set(cacheKey, { stored_at_ms: Date.now(), payload });
  }

  async #request(payload) {
    await this.#ensureWorker();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(payload.id);
        reject(new Error("route worker timeout"));
      }, WORKER_REQUEST_TIMEOUT_MS);
      this.#pending.set(payload.id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.#child.stdin.write(`${JSON.stringify(payload)}\n`);
    });
  }

  async #ensureWorker() {
    if (this.#child && !this.#child.killed) return;
    const child = spawn(
      this.#python,
      ["-m", this.#moduleName, "route-worker"],
      {
        cwd: this.#runtimeRoot,
        env: process.env,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    this.#child = child;
    const rl = readline.createInterface({ input: child.stdout });
    rl.on("line", (line) => {
      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch {
        return;
      }
      const pending = this.#pending.get(parsed.id);
      if (!pending) return;
      this.#pending.delete(parsed.id);
      if (parsed.ok === false) pending.reject(new Error(parsed.error || "route worker error"));
      else pending.resolve({ ...parsed, transport: "worker" });
    });
    child.on("close", () => {
      this.#child = null;
      for (const [, pending] of this.#pending) {
        pending.reject(new Error("route worker exited"));
      }
      this.#pending.clear();
    });
    child.stderr.on("data", () => {});
  }

  async #fallbackSubprocess(payload, workerError) {
    const args = [
      "-m",
      this.#moduleName,
      "route",
      "--root",
      payload.root,
      "--mode",
      payload.mode || "auto",
      "--json",
      "--slim",
    ];
    if (payload.rules_only) args.push("--rules-only");
    if (payload.router_mode) args.push("--router-mode", payload.router_mode);
    args.push(payload.message);

    const completed = await runCommand([this.#python, ...args], this.#runtimeRoot);
    if (completed.code !== 0) {
      throw workerError || new Error(completed.stderr || completed.stdout || "route subprocess failed");
    }
    try {
      return { ...JSON.parse(completed.stdout), ok: true, transport: "subprocess" };
    } catch {
      throw workerError || new Error("route subprocess returned invalid JSON");
    }
  }
}

export function workspaceRouteFingerprint(workspaceRoot) {
  const sessionPath = path.join(workspaceRoot, ".asteria", "current_session.json");
  let sessionStamp = 0;
  let runStamp = 0;
  let phase = "none";
  if (existsSync(sessionPath)) {
    sessionStamp = statSync(sessionPath).mtimeMs;
    try {
      const session = JSON.parse(readFileSync(sessionPath, "utf8"));
      const runId = String(session.session_id || session.run_id || "").trim();
      if (runId) {
        const runPath = path.join(workspaceRoot, ".asteria", "runs", runId, "run.json");
        if (existsSync(runPath)) {
          runStamp = statSync(runPath).mtimeMs;
          const run = JSON.parse(readFileSync(runPath, "utf8"));
          phase = `${run.status || ""}|${run.current_phase || ""}`;
        }
      }
    } catch {
      phase = "unreadable";
    }
  }
  return `${sessionStamp}:${runStamp}:${phase}`;
}

function buildCacheKey({ workspace, message, requestedMode, rulesOnly, routerMode, fingerprint }) {
  const digest = createHash("sha256")
    .update(String(message || ""))
    .digest("hex")
    .slice(0, 16);
  return `${workspace}|${requestedMode}|${rulesOnly ? "rules" : "model"}|${routerMode || "policy"}|${fingerprint}|${digest}`;
}

function runCommand(command, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command[0], command.slice(1), { cwd, env: process.env, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString("utf8"); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.on("error", (error) => resolve({ code: 1, stdout, stderr: String(error) }));
  });
}
