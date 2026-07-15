// White-box source-presence guard (anti-rename canary) — NOT a behavior test. Each assertion only
// proves a clamp-related symbol still exists in the source; green does NOT prove the output actually
// clamps/expands at runtime (that needs a black-box smoke rendering the components).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const clamped = readFileSync(path.join(root, "src/components/ClampedOutput.tsx"), "utf8");
const live = readFileSync(path.join(root, "src/features/thread/LiveStream.tsx"), "utf8");
const eventCard = readFileSync(path.join(root, "src/components/EventCard.tsx"), "utf8");

assert.match(clamped, /clampedOutputCopy/, "`clampedOutputCopy` present in ClampedOutput.tsx");
assert.match(clamped, /maxLines = 8/, "`maxLines = 8` default present in ClampedOutput.tsx");
assert.match(
  live,
  /defaultExpanded={expandOutput}/,
  "`defaultExpanded={expandOutput}` present in LiveStream.tsx",
);
assert.match(eventCard, /tool_observation/, "`tool_observation` present in EventCard.tsx");

console.log("tool-output-clamp source-presence smoke passed");
