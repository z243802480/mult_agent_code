#!/usr/bin/env node
/**
 * Studio smoke runner + coverage manifest.
 *
 * Background: ~40 `studio/scripts/*-smoke.mjs` files existed but NONE ran in CI (CI only ran lint /
 * typecheck / 6 vitest files / 2 Playwright specs). "We have 40 Studio smokes" was an illusion — the
 * chronically-red ones stayed red for weeks because nothing exercised them. This runner ends that:
 *
 *   1. It discovers every runnable smoke on disk (`*-smoke.mjs` / `*-unit.mjs` / `*-contract.mjs`).
 *   2. It fails loudly if any discovered smoke is NOT classified below — so a newly added smoke can't
 *      quietly escape coverage. No silent gaps.
 *   3. CI runs the HERMETIC bucket (no provider key needed). The REQUIRES_MODEL bucket is skipped in
 *      keyless CI and printed with a reason — it is a real-model gate run manually / with keys, never
 *      hidden. `--with-model` runs it too (needs AGENT_MODEL_API_KEY).
 *
 * Usage:
 *   node scripts/run-smokes.mjs              # run hermetic smokes (what CI runs)
 *   node scripts/run-smokes.mjs --with-model # also run real-model smokes (needs a provider key)
 *   node scripts/run-smokes.mjs --list       # print the classification and exit
 */
import { readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const studioDir = path.resolve(scriptsDir, "..");

// Hermetic smokes: pass with every provider credential stripped (verified against a keyless env, the
// exact condition CI runs under). These are the CI set.
const HERMETIC = [
  "beta-workflow-smoke.mjs",
  "chat-execute-handoff-smoke.mjs",
  "chat-fallback-smoke.mjs",
  "chat-lifecycle-smoke.mjs",
  "chat-stream-final-smoke.mjs",
  "composer-side-ask-smoke.mjs",
  "decision-guidance-smoke.mjs",
  "friendly-ssl-error-smoke.mjs",
  "git-changes-smoke.mjs",
  "homepage-copy-smoke.mjs",
  "intent-router-unit.mjs",
  "north-star-inspector-smoke.mjs",
  "orchestration-route-smoke.mjs",
  "permission-level-unit.mjs",
  "preview-proxy-smoke.mjs",
  "preview-serve-smoke.mjs",
  "run-detail-smoke.mjs",
  "s20-worker-promotion-smoke.mjs",
  "s33-friction-contract-smoke.mjs",
  "s45-parity-smoke.mjs",
  "s68-workflow-monitor-smoke.mjs",
  "s71-thread-workflow-smoke.mjs",
  "s8-resume-continuation-smoke.mjs",
  "session-id-smoke.mjs",
  "session-lifecycle-smoke.mjs",
  "session-replay-export-smoke.mjs",
  "snapshot-rollback-smoke.mjs",
  "session-main-path-contract.mjs",
  "side-chat-smoke.mjs",
  "studio-warm-continuation-route-smoke.mjs",
  "tool-output-clamp-smoke.mjs",
  "turn-rewind-smoke.mjs",
  "user-thread-copy-smoke.mjs",
  "workspace-files-smoke.mjs",
  "workspace-switcher-smoke.mjs",
];

// Real-model smokes: genuinely call a provider (chat/plan answers, hybrid intent classification, a
// full run). They cannot pass in keyless CI; without a key they error "API key is not configured" or
// time out waiting for a model answer. Run them with `--with-model` and a provider configured.
const REQUIRES_MODEL = {
  "b6-restricted-user-sim.mjs": "boots a full run and fails model-check on the strong model",
  "intent-routing-smoke.mjs": "waits on real chat answers + plan/run jobs the model must produce",
  "plan-output-smoke.mjs": "asserts a real model-generated plan answer",
  "orchestration-route-worker-smoke.mjs": "hybrid router calls MiniMax to classify intent",
};

// `*-benchmark.mjs` is a manual latency/quality benchmark, not a pass/fail smoke — excluded from
// discovery by suffix. Playwright `*.spec.mjs` run in the separate `test:ui` job. Helpers are libs.
const NON_SMOKE = new Set(["studio-fixture.mjs", "server-surface.mjs", "run-smokes.mjs"]);

function discoverSmokes() {
  return readdirSync(scriptsDir)
    .filter((f) => /-(smoke|unit|contract|sim)\.mjs$/.test(f))
    .filter((f) => !f.endsWith(".spec.mjs"))
    .filter((f) => !NON_SMOKE.has(f))
    .sort();
}

function validateManifest(discovered) {
  const classified = new Set([...HERMETIC, ...Object.keys(REQUIRES_MODEL)]);
  const unclassified = discovered.filter((f) => !classified.has(f));
  const missing = [...classified].filter((f) => !discovered.includes(f));
  const errors = [];
  if (unclassified.length) {
    errors.push(
      `Unclassified smoke(s) on disk — add each to HERMETIC or REQUIRES_MODEL in run-smokes.mjs:\n  ${unclassified.join("\n  ")}`,
    );
  }
  if (missing.length) {
    errors.push(`Manifest lists file(s) that no longer exist:\n  ${missing.join("\n  ")}`);
  }
  const overlap = HERMETIC.filter((f) => f in REQUIRES_MODEL);
  if (overlap.length) errors.push(`Smoke(s) in both buckets: ${overlap.join(", ")}`);
  return errors;
}

function runOne(file) {
  const started = Date.now();
  const res = spawnSync("node", [path.join(scriptsDir, file)], {
    cwd: studioDir,
    encoding: "utf8",
    timeout: 120000,
    env: process.env,
  });
  const ms = Date.now() - started;
  if (res.status === 0) return { file, ok: true, ms };
  const tail = (res.stderr || res.stdout || "")
    .trim()
    .split("\n")
    .filter((l) => /Error|assert|expected|Timed out|too slow|got |missing/.test(l))
    .slice(-1)[0];
  return { file, ok: false, ms, reason: (tail || `exit ${res.status}`).slice(0, 200) };
}

const args = process.argv.slice(2);
const withModel = args.includes("--with-model");
const listOnly = args.includes("--list");

const discovered = discoverSmokes();
const manifestErrors = validateManifest(discovered);
if (manifestErrors.length) {
  console.error("Smoke manifest is out of sync:\n\n" + manifestErrors.join("\n\n"));
  process.exit(2);
}

if (listOnly) {
  console.log(`Hermetic (CI) — ${HERMETIC.length}:`);
  for (const f of HERMETIC) console.log(`  ${f}`);
  console.log(`\nRequires model (skipped in CI) — ${Object.keys(REQUIRES_MODEL).length}:`);
  for (const [f, why] of Object.entries(REQUIRES_MODEL)) console.log(`  ${f}  — ${why}`);
  process.exit(0);
}

console.log(
  `Studio smokes: ${HERMETIC.length} hermetic (running), ${Object.keys(REQUIRES_MODEL).length} real-model.`,
);

const toRun = [...HERMETIC];
if (withModel) {
  const hasKey = process.env.AGENT_MODEL_API_KEY || process.env.AGENT_MODEL_STRONG_API_KEY;
  if (hasKey) toRun.push(...Object.keys(REQUIRES_MODEL));
  else
    console.log(
      "--with-model requested but no AGENT_MODEL_API_KEY set; skipping real-model smokes.",
    );
}

const results = [];
for (const file of toRun) {
  const r = runOne(file);
  results.push(r);
  console.log(`  ${r.ok ? "PASS" : "FAIL"}  ${file}  (${r.ms}ms)${r.ok ? "" : "  :: " + r.reason}`);
}

// Always name what was held out — an honest ledger, never a silent gap.
const skipped = Object.entries(REQUIRES_MODEL).filter(([f]) => !toRun.includes(f));
if (skipped.length) {
  console.log(`\nHeld out (real-model gate, run with --with-model + a provider key):`);
  for (const [f, why] of skipped) console.log(`  SKIP  ${f}  — ${why}`);
}

const failed = results.filter((r) => !r.ok);
console.log(
  `\n==== ${results.length} run, ${results.length - failed.length} pass, ${failed.length} fail ====`,
);
if (failed.length) {
  console.error("FAILED: " + failed.map((r) => r.file).join(", "));
  process.exit(1);
}
console.log("All studio smokes passed.");
