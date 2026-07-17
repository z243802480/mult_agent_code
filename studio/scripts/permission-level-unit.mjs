import assert from "node:assert/strict";
import { mapPermissionLevel, warmRunParams, withPermissionLevel } from "../lib/permission-level.mjs";

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

// The whole point of warmRunParams: the cold path (a CLI flag) and the warm path (a JSON field) must
// carry the SAME tier. If they ever drift, the failure is silent and it always errs toward MORE
// autonomy (studio_worker defaults to "balanced"), so no user would see it happen.
check("warm request and cold command agree on the tier, for every mode", () => {
  for (const mode of ["ask_everything", "reviewed_auto", "auto", "nonsense", ""]) {
    const cold = withPermissionLevel(
      ["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"],
      mapPermissionLevel(mode),
    );
    const flagIndex = cold.indexOf("--permission-level");
    assert.notEqual(flagIndex, -1, `cold command carries no tier for ${mode}`);
    assert.equal(
      cold[flagIndex + 1],
      warmRunParams(mode).permission_level,
      `cold/warm disagree for ${mode}`,
    );
  }
});

check("warmRunParams degrades an unknown tier the same way the flag does", () => {
  assert.deepEqual(warmRunParams("nonsense"), { permission_level: "balanced" });
  assert.deepEqual(warmRunParams("ask_everything"), { permission_level: "ask" });
});

console.log(`\n${passed} checks passed`);
