import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const serverSource = readFileSync(path.join(root, "studio/server.mjs"), "utf8");

assert.match(
  serverSource,
  /replan:\s*"continue"/,
  "Studio runtimeActionFor must map replan → continue for session_agent friction path",
);

const b6Source = readFileSync(path.join(root, "studio/scripts/b6-restricted-user-sim.mjs"), "utf8");
assert.match(
  b6Source,
  /startsWith\("replan"\).*return\s*"resume"/,
  "B6 sim must map replan → resume",
);

console.log("S33 friction contract smoke passed");
