import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const thread = readFileSync(path.join(studioDir, "src/features/thread/Thread.tsx"), "utf8");
const runtimeSnapshot = readFileSync(path.join(studioDir, "src/features/thread/RuntimeSnapshot.tsx"), "utf8");
const app = readFileSync(path.join(studioDir, "src/App.tsx"), "utf8");
const permissionCard = readFileSync(path.join(studioDir, "src/components/PermissionCard.tsx"), "utf8");
const eventCard = readFileSync(path.join(studioDir, "src/components/EventCard.tsx"), "utf8");

assert.ok(!thread.includes("WorkflowMonitorCompact"), "internal workflow monitor must stay out of the main session");
assert.ok(!runtimeSnapshot.includes("PermissionCard"), "permission requests must render once in the session timeline");
assert.ok(runtimeSnapshot.includes("Review changes"), "accept-ready state must expose a read-only review action");
assert.ok(app.includes("openReviewFile") && app.includes("openTurnReview"), "session diff actions must open the review surface");
assert.ok(permissionCard.includes("permission_preview"), "permission card must consume semantic preview data");
assert.ok(!permissionCard.includes("event.command"), "permission card must not expose raw commands");
assert.ok(!eventCard.includes("event.command"), "main-session event cards must not expose raw commands");

// Match the per-turn map by its stable callback arg, not the array identifier (the rendered list may
// be a windowed slice, e.g. visibleTurns.map, without changing that turns render before the snapshot).
const turnPosition = thread.indexOf(".map((turnSteps");
const actionPosition = thread.lastIndexOf("<RuntimeSnapshot");
assert.ok(turnPosition >= 0, "main session must render conversation turns");
assert.ok(actionPosition > turnPosition, "next action must follow the conversation instead of leading it");

console.log("session-main-path contract passed");
