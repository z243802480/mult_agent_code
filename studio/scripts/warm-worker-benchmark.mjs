// Cold-vs-warm startup benchmark for the Studio warm worker (ADR-0029 ②).
//
// What it measures: the wall-clock cost of bringing a runtime process to the point where it can
// start executing a run — i.e. Python interpreter start + the ~50-module import graph + factory
// import. In the COLD model this is paid on every single run (each run is a fresh
// `python -m asteria_runtime run …`). In the WARM model it is paid ONCE at boot and then reused, so
// every run after the first starts warm. This benchmark spawns the worker N times and times each
// spawn→`ready`; that per-spawn number IS the cold cost the warm worker removes from every run.
//
// It deliberately does NOT run a real agent turn (that needs a provider), so this stays deterministic
// and offline. Excluded from the smoke suite (name ends in -benchmark.mjs). Run manually:
//   node scripts/warm-worker-benchmark.mjs
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PREFIX = "@@ASTERIA_WORKER@@ ";
const TRIALS = 3;

function timeSpawnToReady() {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    const child = spawn("python", ["-m", "asteria_runtime.studio_worker"], {
      cwd: repoRoot,
      env: { ...process.env, PYTHONPATH: "src", PYTHONIOENCODING: "utf-8" },
    });
    let buf = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("timeout waiting for ready"));
    }, 30000);
    child.stdout.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        if (line.startsWith(PREFIX) && JSON.parse(line.slice(PREFIX.length)).event === "ready") {
          clearTimeout(timer);
          const ms = Date.now() - t0;
          child.stdin.end();
          child.kill();
          resolve(ms);
        }
      }
    });
    child.stderr.on("data", () => {});
    child.on("error", reject);
  });
}

(async () => {
  const samples = [];
  for (let i = 0; i < TRIALS; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    samples.push(await timeSpawnToReady());
  }
  const mean = Math.round(samples.reduce((a, b) => a + b, 0) / samples.length);
  console.log(`cold start→ready over ${TRIALS} trials: [${samples.join(", ")}] ms`);
  console.log(
    `mean cold startup = ${mean}ms  (paid on EVERY cold run; the warm worker pays it once)`,
  );
  console.log(
    `warm run startup ≈ 0ms (reuses the resident process) → ~${mean}ms shaved off each run after boot`,
  );
})();
