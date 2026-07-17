import assert from "node:assert/strict";
import {
  MODEL_STRATEGY_IDS,
  MODEL_TIERS,
  mapModelNames,
  mapModelStrategy,
  mapPermissionLevel,
  warmRunParams,
  withModelNames,
  withModelStrategy,
  withPermissionLevel,
} from "../lib/run-flags.mjs";

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

check("splices --model-strategy the same way, and only into a run", () => {
  const run = ["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"];
  assert.deepEqual(withModelStrategy(run, "economy"), [
    "python",
    "-m",
    "asteria_runtime",
    "run",
    "--model-strategy",
    "economy",
    "--root",
    "ws",
    "goal",
  ]);
  const review = ["python", "-m", "asteria_runtime", "review", "--root", "ws"];
  assert.deepEqual(withModelStrategy(review, "quality"), review); // no run token -> untouched
  assert.deepEqual(withModelStrategy(run, ""), run); // no strategy -> untouched
  const already = [...run.slice(0, 4), "--model-strategy", "local", ...run.slice(4)];
  assert.deepEqual(withModelStrategy(already, "quality"), already); // never double-adds
});

check("both flags coexist without clobbering each other", () => {
  const cmd = withModelStrategy(
    withPermissionLevel(["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"], "ask"),
    "economy",
  );
  assert.equal(cmd[cmd.indexOf("--permission-level") + 1], "ask");
  assert.equal(cmd[cmd.indexOf("--model-strategy") + 1], "economy");
  assert.equal(cmd[cmd.length - 1], "goal", "the goal must stay last");
});

check("mapModelStrategy degrades anything unknown to the argparse default", () => {
  assert.equal(mapModelStrategy("nonsense"), "auto");
  assert.equal(mapModelStrategy(""), "auto");
  assert.equal(mapModelStrategy(undefined), "auto");
  assert.equal(mapModelStrategy("ECONOMY"), "economy");
  for (const id of MODEL_STRATEGY_IDS) assert.equal(mapModelStrategy(id), id);
});

// The whole point of warmRunParams: the cold path (CLI flags) and the warm path (JSON fields) must
// carry the SAME choices. If they ever drift the failure is silent — the tier errs toward MORE
// autonomy (studio_worker defaults to "balanced") and the strategy silently reverts to "auto", so no
// user would see either happen. Cross-product, because a future edit could couple them by accident.
check("warm request and cold command agree on every choice, for every combination", () => {
  for (const mode of ["ask_everything", "reviewed_auto", "auto", "nonsense", ""]) {
    for (const strategy of [...MODEL_STRATEGY_IDS, "nonsense", ""]) {
      const base = ["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"];
      const cold = withModelStrategy(
        withPermissionLevel(base, mapPermissionLevel(mode)),
        mapModelStrategy(strategy),
      );
      const warm = warmRunParams(mode, strategy);
      const where = `${mode || "<empty>"}/${strategy || "<empty>"}`;

      const tierIndex = cold.indexOf("--permission-level");
      assert.notEqual(tierIndex, -1, `cold command carries no tier for ${where}`);
      assert.equal(cold[tierIndex + 1], warm.permission_level, `cold/warm tier differ at ${where}`);

      const strategyIndex = cold.indexOf("--model-strategy");
      assert.notEqual(strategyIndex, -1, `cold command carries no strategy for ${where}`);
      assert.equal(
        cold[strategyIndex + 1],
        warm.model_strategy,
        `cold/warm strategy differ at ${where}`,
      );
    }
  }
});

check("warmRunParams degrades unknown values the same way the flags do", () => {
  assert.deepEqual(warmRunParams("nonsense", "nonsense"), {
    permission_level: "balanced",
    model_strategy: "auto",
    model_name_overrides: {},
  });
  assert.deepEqual(warmRunParams("ask_everything", "quality", { strong: "glm-4.6" }), {
    permission_level: "ask",
    model_strategy: "quality",
    model_name_overrides: { strong: "glm-4.6" },
  });
});

check("mapModelNames drops what the runtime would drop", () => {
  assert.deepEqual(mapModelNames({ strong: "glm-4.6" }), { strong: "glm-4.6" });
  assert.deepEqual(mapModelNames({ STRONG: "  glm-4.6  " }), { strong: "glm-4.6" });
  assert.deepEqual(mapModelNames({ bogus: "x" }), {}); // unknown tier
  assert.deepEqual(mapModelNames({ strong: "" }), {}); // blank is "no pin", not a model named ""
  assert.deepEqual(mapModelNames({ strong: null }), {});
  assert.deepEqual(mapModelNames("nope"), {});
  assert.deepEqual(mapModelNames(null), {});
});

// The trap this test exists for: withRunFlag bails out when the command already carries the flag, so
// looping it per tier would emit ONLY the first pin and silently drop the rest.
check("every pinned tier reaches the command, not just the first", () => {
  const cmd = withModelNames(["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"], {
    strong: "glm-4.6",
    medium: "MiniMax-M2",
    cheap: "glm-4.5-air",
  });
  const pairs = cmd.filter((_, i) => cmd[i - 1] === "--model-name");
  assert.deepEqual(pairs, ["cheap=glm-4.5-air", "medium=MiniMax-M2", "strong=glm-4.6"]);
  assert.equal(cmd[cmd.length - 1], "goal", "the goal must stay last");
});

check("withModelNames leaves a command alone when there is nothing to pin", () => {
  const cmd = ["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"];
  assert.deepEqual(withModelNames(cmd, {}), cmd);
  assert.deepEqual(withModelNames(cmd, { bogus: "x" }), cmd); // normalizes to nothing
  assert.deepEqual(withModelNames(cmd, null), cmd);
  const review = ["python", "-m", "asteria_runtime", "review", "--root", "ws"];
  assert.deepEqual(withModelNames(review, { strong: "x" }), review); // no run token
});

// Same invariant as the tier/strategy pair above, extended to the third choice: the cold path (N
// flags) and the warm path (a JSON map) must agree tier by tier. This one has more room to drift —
// one is a flat token list, the other a map — so it is checked structurally, not by string compare.
check("cold flags and warm map agree tier-by-tier on every pin shape", () => {
  const shapes = [
    {},
    { strong: "glm-4.6" },
    { strong: "glm-4.6", cheap: "glm-4.5-air" },
    { strong: "a", medium: "b", cheap: "c" },
    { strong: "  spaced  ", bogus: "dropped", medium: "" },
    null,
  ];
  for (const shape of shapes) {
    const base = ["python", "-m", "asteria_runtime", "run", "--root", "ws", "goal"];
    const cold = withModelNames(base, shape);
    const warm = warmRunParams("auto", "auto", shape).model_name_overrides;
    const fromCold = {};
    cold.forEach((token, index) => {
      if (cold[index - 1] !== "--model-name") return;
      const [tier, ...rest] = token.split("=");
      fromCold[tier] = rest.join("=");
    });
    assert.deepEqual(fromCold, warm, `cold/warm pins differ for ${JSON.stringify(shape)}`);
    for (const tier of Object.keys(warm)) {
      assert.ok(MODEL_TIERS.includes(tier), `warm map leaked a non-tier key: ${tier}`);
    }
  }
});

console.log(`\n${passed} checks passed`);
