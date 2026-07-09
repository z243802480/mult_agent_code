import assert from "node:assert/strict";
import { mapPermissionLevel, withPermissionLevel } from "../lib/permission-level.mjs";

let passed = 0;
function check(name, fn) {
  fn();
  passed += 1;
  console.log(`ok - ${name}`);
}

check("ask_everything -> ask", () => assert.equal(mapPermissionLevel("ask_everything"), "ask"));
check("reviewed_auto -> balanced", () =>
  assert.equal(mapPermissionLevel("reviewed_auto"), "balanced"),
);
check("auto -> auto", () => assert.equal(mapPermissionLevel("auto"), "auto"));
check("unknown -> balanced (product default)", () =>
  assert.equal(mapPermissionLevel("nonsense"), "balanced"),
);
check("empty -> balanced", () => assert.equal(mapPermissionLevel(""), "balanced"));

check("splices --permission-level right after the run token", () => {
  const cmd = ["python", "-m", "asteria_runtime", "run", "--root", "ws", "--no-research", "goal"];
  assert.deepEqual(withPermissionLevel(cmd, "auto"), [
    "python",
    "-m",
    "asteria_runtime",
    "run",
    "--permission-level",
    "auto",
    "--root",
    "ws",
    "--no-research",
    "goal",
  ]);
});

check("works for run --continue-session", () => {
  const cmd = [
    "python",
    "-m",
    "asteria_runtime",
    "run",
    "--continue-session",
    "--root",
    "ws",
    "goal",
  ];
  assert.deepEqual(withPermissionLevel(cmd, "ask"), [
    "python",
    "-m",
    "asteria_runtime",
    "run",
    "--permission-level",
    "ask",
    "--continue-session",
    "--root",
    "ws",
    "goal",
  ]);
});

check("module name asteria_runtime never false-matches 'run'", () => {
  const cmd = ["python", "-m", "asteria_runtime", "plan", "--root", "ws", "goal"];
  assert.deepEqual(withPermissionLevel(cmd, "auto"), cmd); // unchanged: no exact 'run' token
});

check("never double-adds the flag", () => {
  const cmd = [
    "python",
    "-m",
    "asteria_runtime",
    "run",
    "--permission-level",
    "ask",
    "--root",
    "ws",
  ];
  assert.deepEqual(withPermissionLevel(cmd, "auto"), cmd);
});

check("no level -> command unchanged", () => {
  const cmd = ["python", "-m", "asteria_runtime", "run", "--root", "ws"];
  assert.deepEqual(withPermissionLevel(cmd, ""), cmd);
});

check("review command (no run token) unchanged", () => {
  const cmd = ["python", "-m", "asteria_runtime", "review", "--root", "ws"];
  assert.deepEqual(withPermissionLevel(cmd, "balanced"), cmd);
});

console.log(`\n${passed} checks passed`);
