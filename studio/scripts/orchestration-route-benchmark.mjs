/**
 * Orchestration route benchmark — compare hybrid/rules/model latency and capability picks.
 *
 * Usage:
 *   node studio/scripts/orchestration-route-benchmark.mjs
 *   node studio/scripts/orchestration-route-benchmark.mjs --root h:/mult_agent_code
 */
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const python = process.env.ASTERIA_PYTHON || "python";

const args = process.argv.slice(2);
const rootArgIndex = args.indexOf("--root");
const workspace = rootArgIndex >= 0 ? path.resolve(args[rootArgIndex + 1]) : repoRoot;
const skipModel = args.includes("--rules-only");

const cases = [
  {
    id: "simple_qa",
    label: "简单问答",
    message: "Python 里 list 和 tuple 有什么区别？",
    expect: "chat_answer",
  },
  {
    id: "status_q",
    label: "状态询问",
    message: "当前项目下一步是什么？",
    expect: "chat_answer",
  },
  {
    id: "cold_edit",
    label: "冷启动改代码",
    message: "给 greet_cli 增加 --version 参数并补测试",
    expect: "cold_goal_execute",
    coldOnly: true,
  },
  {
    id: "warm_edit",
    label: "warm 续作",
    message: "再给 greet_cli 增加 --quiet 参数并补测试",
    expect: "session_continue_execute",
    warmOnly: true,
  },
  {
    id: "read_only",
    label: "只读分析",
    message: "先分析 greet_cli 架构，不要改文件",
    expect: "read_only_plan",
  },
  {
    id: "ambiguous",
    label: "模糊意图",
    message: "帮我想想怎么改 greet_cli，但先别动手",
    expect: "read_only_plan",
    allowModel: true,
  },
];

const warmWorkspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-route-bench-warm-"));
await setupAcceptedWorkspace(warmWorkspace);

const results = [];
for (const testCase of cases) {
  const roots = [];
  if (!testCase.warmOnly) roots.push({ name: "repo", root: workspace });
  if (!testCase.coldOnly) roots.push({ name: "warm", root: warmWorkspace });

  for (const target of roots) {
    const hybrid = await routeOnce(target.root, testCase.message, false, "hybrid");
    const rules = await routeOnce(target.root, testCase.message, true);
    const model = skipModel ? null : await routeOnce(target.root, testCase.message, false, "model");

    results.push({
      id: testCase.id,
      label: testCase.label,
      workspace: target.name,
      message: testCase.message,
      expect: testCase.expect,
      hybrid,
      rules,
      model,
    });
  }
}

printReport(results);

async function routeOnce(root, message, rulesOnly, routerMode) {
  const started = performance.now();
  const argv = ["-m", "asteria_runtime", "route", "--root", root, "--json"];
  if (rulesOnly) argv.push("--rules-only");
  if (routerMode) argv.push("--router-mode", routerMode);
  argv.push(message);
  const payload = JSON.parse(await runPythonCapture(argv));
  const elapsedMs = Math.round(performance.now() - started);
  return {
    capability_id: payload.capability_id,
    source: payload.source,
    studio_mode: payload.studio_mode,
    reason: String(payload.reason || "").slice(0, 120),
    elapsed_ms: elapsedMs,
    ok: payload.capability_id,
  };
}

function printReport(results) {
  console.log("\n=== Orchestration Route Benchmark ===");
  console.log(`workspace: ${workspace}`);
  console.log(`warm workspace: ${warmWorkspace}`);
  console.log(`model runs: ${skipModel ? "skipped (--rules-only global)" : "included"}\n`);

  let hybridHits = 0;
  let rulesHits = 0;
  let modelHits = 0;
  let hybridFast = 0;
  let total = 0;

  for (const row of results) {
    total += 1;
    const expect = row.expect;
    if (row.hybrid.capability_id === expect) hybridHits += 1;
    if (row.rules.capability_id === expect) rulesHits += 1;
    if (row.model && row.model.capability_id === expect) modelHits += 1;
    if (row.hybrid.source === "fast_path" || row.hybrid.source === "rules") hybridFast += 1;

    console.log(`--- ${row.label} [${row.workspace}] ---`);
    console.log(`  message: ${row.message}`);
    console.log(`  expect:  ${expect}`);
    console.log(
      `  hybrid:  ${row.hybrid.capability_id} (${row.hybrid.source}, ${row.hybrid.elapsed_ms}ms)`,
    );
    console.log(
      `  rules:   ${row.rules.capability_id} (${row.rules.source}, ${row.rules.elapsed_ms}ms)`,
    );
    if (row.model) {
      console.log(
        `  model:   ${row.model.capability_id} (${row.model.source}, ${row.model.elapsed_ms}ms)`,
      );
    }
    console.log("");
  }

  const simpleRows = results.filter((row) => row.expect === "chat_answer");
  const avgHybridSimple =
    simpleRows.reduce((sum, row) => sum + row.hybrid.elapsed_ms, 0) /
    Math.max(simpleRows.length, 1);
  const avgRulesSimple =
    simpleRows.reduce((sum, row) => sum + row.rules.elapsed_ms, 0) / Math.max(simpleRows.length, 1);

  console.log("=== Summary ===");
  console.log(`capability hit rate — hybrid: ${hybridHits}/${total}, rules: ${rulesHits}/${total}`);
  if (!skipModel) console.log(`capability hit rate — pure model mode: ${modelHits}/${total}`);
  console.log(`hybrid fast-path (no model): ${hybridFast}/${total}`);
  console.log(
    `simple Q avg latency — hybrid: ${Math.round(avgHybridSimple)}ms, rules: ${Math.round(avgRulesSimple)}ms`,
  );
  console.log(
    "note: cold run path ~15-25s+ (GoalSpec+Plan); chat_answer route should stay sub-second on hybrid fast path",
  );
}

async function setupAcceptedWorkspace(target) {
  const repo = repoRoot.replace(/\\/g, "/");
  const script = `
from pathlib import Path
import sys
root = Path(sys.argv[1])
repo = Path("${repo}")
sys.path.insert(0, str(repo))
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.integration.test_plan_command import FakePlanClient

InitCommand(root).run()
plan = PlanCommand(root, "Add --version", model_client=FakePlanClient()).run()
validator = SchemaValidator(repo / "schemas")
run_store = RunStore(root / ".asteria", validator)
store = JsonStore(validator)
run_dir = run_store.run_dir(plan.run_id)
run = run_store.load_run(plan.run_id)
run["status"] = "completed"
run["current_phase"] = "ACCEPTED"
run_store.update_run(run)
task_plan = store.read(run_dir / "task_plan.json", "task_board")
for task in task_plan.get("tasks") or []:
    task["status"] = "done"
store.write(run_dir / "task_plan.json", task_plan, "task_board")
run_store.set_current_session(plan.run_id, "orchestration_route_benchmark")
`;
  const completed = await runCommand([python, "-c", script, target], repoRoot);
  if (completed.code !== 0) {
    throw new Error(`workspace setup failed: ${completed.stderr || completed.stdout}`);
  }
}

function runCommand(command, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command[0], command.slice(1), { cwd, env: process.env, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function runPythonCapture(args) {
  const completed = await runCommand([python, ...args], repoRoot);
  if (completed.code !== 0) throw new Error(completed.stderr || completed.stdout);
  return completed.stdout;
}
