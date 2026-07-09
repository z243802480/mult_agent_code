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

const required = [
  "preferredDecisionOptionId",
  "decisionHint",
  "pendingDecisionSummary",
  "runtimeNextStepSummary",
  "review_contract",
  "Allow the expanded scope",
  "A step failed",
  "Approve this command once",
  "repair_limit",
  "replan_budget_exhausted",
];

for (const token of required) {
  if (!source.includes(token) && !runtime.includes(token)) {
    throw new Error(`decision guidance smoke missing token: ${token}`);
  }
}

console.log("decision-guidance smoke passed");
