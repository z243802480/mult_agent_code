import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = readFileSync(
  path.join(studioDir, "src/features/thread/decisionGuidance.ts"),
  "utf8",
);
const runtime = readFileSync(
  path.join(studioDir, "src/features/thread/RuntimeSnapshot.tsx"),
  "utf8",
);

// Assert the structural decision-routing keys — the kinds, option ids and exit reasons that decide
// WHICH hint fires — not the human copy of the hints themselves. The list used to include English
// sentences ("Allow the expanded scope", "A step failed", "Approve this command once"); those went
// red the instant the hints were localized to Chinese, a pure false alarm since the routing was
// untouched. Structural identifiers are locale-independent and are what actually must survive.
const required = [
  "preferredDecisionOptionId",
  "decisionHint",
  "pendingDecisionSummary",
  "runtimeNextStepSummary",
  "review_contract",
  "execution_policy_approval",
  "approve_once",
  "runtime_request",
  "replan_decision",
  "repair_limit",
  "replan_budget_exhausted",
];

for (const token of required) {
  if (!source.includes(token) && !runtime.includes(token)) {
    throw new Error(`decision guidance smoke missing token: ${token}`);
  }
}

console.log("decision-guidance smoke passed");
