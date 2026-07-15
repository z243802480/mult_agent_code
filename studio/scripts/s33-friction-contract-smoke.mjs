// White-box source-presence guard (anti-rename canary) — NOT a behavior test. It only proves the
// replan→continue/resume mapping symbols still exist in the source; green does NOT prove the friction
// path works at runtime (that needs a black-box smoke driving the runtime action).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerSurface } from "./server-surface.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const serverSource = readServerSurface(path.join(root, "studio"));

assert.match(
  serverSource,
  /replan:\s*"continue"/,
  '`replan: "continue"` mapping present in server surface (runtimeActionFor)',
);

const b6Source = readFileSync(path.join(root, "studio/scripts/b6-restricted-user-sim.mjs"), "utf8");
assert.match(
  b6Source,
  /startsWith\("replan"\).*return\s*"resume"/,
  "`replan → resume` mapping present in b6-restricted-user-sim.mjs",
);

console.log("S33 friction source-presence smoke passed");
