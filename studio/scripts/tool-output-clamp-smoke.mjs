import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const clamped = readFileSync(path.join(root, "src/components/ClampedOutput.tsx"), "utf8");
const live = readFileSync(path.join(root, "src/features/thread/LiveStream.tsx"), "utf8");
const eventCard = readFileSync(path.join(root, "src/components/EventCard.tsx"), "utf8");

assert.match(clamped, /clampedOutputCopy/, "ClampedOutput must expose copy action");
assert.match(clamped, /maxLines = 8/, "ClampedOutput default clamp should be ~8 lines");
assert.match(
  live,
  /defaultExpanded={expandOutput}/,
  "LiveStream must expand tool output in Verbose",
);
assert.match(eventCard, /tool_observation/, "EventCard must clamp tool observation bodies");

console.log("tool-output-clamp smoke passed");
