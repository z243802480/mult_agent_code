import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const thread = readFileSync(path.join(studioDir, "src/features/thread/Thread.tsx"), "utf8");
const runtimeSnapshot = readFileSync(
  path.join(studioDir, "src/features/thread/RuntimeSnapshot.tsx"),
  "utf8",
);
const app = readFileSync(path.join(studioDir, "src/App.tsx"), "utf8");
const permissionCard = readFileSync(
  path.join(studioDir, "src/components/PermissionCard.tsx"),
  "utf8",
);
const eventCard = readFileSync(path.join(studioDir, "src/components/EventCard.tsx"), "utf8");
const runtimeNarrative = readFileSync(
  path.join(studioDir, "src/features/thread/runtimeNarrative.ts"),
  "utf8",
);
const conversationTurn = readFileSync(
  path.join(studioDir, "src/features/thread/ConversationTurn.tsx"),
  "utf8",
);
const narrative = readFileSync(path.join(studioDir, "src/narrative.ts"), "utf8");
const runtimeSnapshotSrc = readFileSync(
  path.join(studioDir, "src/features/thread/RuntimeSnapshot.tsx"),
  "utf8",
);

assert.ok(
  !thread.includes("WorkflowMonitorCompact"),
  "internal workflow monitor must stay out of the main session",
);
assert.ok(
  !runtimeSnapshot.includes("PermissionCard"),
  "permission requests must render once in the session timeline",
);
assert.ok(
  runtimeSnapshot.includes("查看改动") && runtimeSnapshot.includes("onOpenReview"),
  "accept-ready state must expose a read-only review action",
);
assert.ok(
  app.includes("openReviewFile") && app.includes("openTurnReview"),
  "session diff actions must open the review surface",
);
assert.ok(
  permissionCard.includes("permission_preview"),
  "permission card must consume semantic preview data",
);
assert.ok(
  !permissionCard.includes("event.command"),
  "permission card must not expose raw commands",
);
assert.ok(
  !eventCard.includes("event.command"),
  "main-session event cards must not expose raw commands",
);

// Match the per-turn map by its stable callback arg, not the array identifier (the rendered list may
// be a windowed slice, e.g. visibleTurns.map, without changing that turns render before the snapshot).
const turnPosition = thread.indexOf(".map((turnSteps");
const actionPosition = thread.lastIndexOf("<RuntimeSnapshot");
assert.ok(turnPosition >= 0, "main session must render conversation turns");
assert.ok(
  actionPosition > turnPosition,
  "next action must follow the conversation instead of leading it",
);

// The /run loop now emits a real executable-verification verdict; the "not yet verified, run Review"
// hint must defer to that verdict (pass => no nag, fail => explicit failure) instead of always
// telling a UX user their verified work is unverified.
assert.ok(
  runtimeNarrative.includes("latestCorrectnessVerdict"),
  "run verification hint must read the recorded executable-verification verdict",
);
assert.ok(
  /verdict === "pass"[\s\S]*?return ""/.test(runtimeNarrative),
  "a passing verification verdict must suppress the unverified nag",
);
assert.ok(
  /verdict === "fail"/.test(runtimeNarrative),
  "a failing verification verdict must be surfaced, not hidden",
);
// The verdict must be identified by its machine marker (telemetry.correctness_status), NOT merely
// by transcript_kind==="verification": generic review steps (e.g. "Validation conclusion") reuse
// that kind and are emitted AFTER the verdict, so kind-only scanning lets them shadow a real pass
// and wrongly nag the user. Lock the discriminator so that regression can't return.
assert.ok(
  /correctness_status/.test(runtimeNarrative),
  "verdict detection must key off telemetry.correctness_status, not transcript_kind alone",
);

// Honesty gate for the green "验证通过" badge: it must be bound to THIS turn's own verification, not
// just the run-global latest verdict. Otherwise a turn that did no verification of its own (e.g. a
// resumed/replayed turn whose stated goal differs from the verified work) inherits an earlier pass
// and falsely claims the new request "verified" — the goal-swallowing dishonesty. Lock both halves:
// the turn-scoped verdict exists and reads this turn's step events keyed off correctness_status, and
// the badge condition requires it to agree with the run-level pass.
assert.ok(
  /export function turnCorrectnessVerdict\([\s\S]*?steps\.flatMap\([\s\S]*?correctness_status/.test(
    runtimeNarrative,
  ),
  "turnCorrectnessVerdict must scan this turn's own step events, keyed off correctness_status",
);
// The badge condition was refactored out of an inline expression into the turnVerifiedBadge helper
// (answerLed work), so assert the CURRENT honest structure rather than the old inline wording: the
// badge is fed THIS turn's own verdict (turnCorrectnessVerdict(steps)), and the helper only returns
// true when that turn-scoped verdict is "pass" — a turn that did no verification of its own reads
// "unrun" and gets no badge, which is the goal-swallowing dishonesty this locks out.
assert.ok(
  /const verifiedPass = turnVerifiedBadge\(\{[\s\S]*?turnVerdict: turnCorrectnessVerdict\(steps\)/.test(
    conversationTurn,
  ),
  "the verified-pass badge must be fed THIS turn's own verdict (turnVerifiedBadge ← turnCorrectnessVerdict(steps)), not a run-global latest",
);
assert.ok(
  /export function turnVerifiedBadge\([\s\S]*?return turnVerdict === "pass"/.test(runtimeNarrative),
  "turnVerifiedBadge must gate strictly on the turn-scoped verdict being pass",
);

// Main-thread scaffolding cut: the loop's own bookkeeping steps (turn/iteration markers, context
// mounts, recorded-decision observations) are DROPPED from the thread entirely, not merely un-styled.
// buildRunNarrative must skip a set of machinery kinds so neither the live nor the completed view can
// resurface "执行迭代 N" / "上下文关联" / "已选择权限模式". Lock the drop-set and the drop itself.
assert.ok(
  /MACHINERY_KINDS[\s\S]*?"turn"[\s\S]*?"context"[\s\S]*?"observation"/.test(narrative),
  "narrative must define a machinery drop-set covering turn/context/observation",
);
assert.ok(
  /if \(MACHINERY_KINDS\.has\(kind\)\) continue;/.test(narrative),
  "buildRunNarrative must drop machinery-kind steps from the thread",
);
// Ceremony/notice events are filtered by STABLE STRUCTURAL MARKERS, never by localized title text:
// the goal-accept ritual ("理解目标", phase=understand), context mounts (transcript_kind=context_status),
// and auto-replan control-flow notices ("自动重规划已创建修复任务", transcript_kind=repair while NOT
// failed). A genuine failure (status=failed) must still surface.
assert.ok(
  /=== "understand"/.test(narrative) && /=== "context_status"/.test(narrative),
  "isInternalLoopScaffolding must drop the understand-phase ceremony and context mounts",
);
assert.ok(
  /=== "repair" && event\.status !== "failed"/.test(narrative),
  "auto-replan repair NOTICES are dropped, but a genuine failure (status=failed) is kept",
);
// A recorded permission/capability decision carries a job_id but is NOT a pending ask — it must fold
// to observation (machinery), not render as a dead tool card. Only a waiting_user job ask is the
// actionable PermissionCard. Lock the waiting_user gate so the "已选择权限模式" card can't come back.
assert.ok(
  /event\.job_id && event\.status === "waiting_user"\) return "tool"/.test(narrative),
  "only a PENDING (waiting_user) job ask maps to a tool/PermissionCard; recorded decisions fold to observation",
);

// A CLEAN completion (exit_reason completed/stop) must not keep a dead "已停止: completed" next-step
// bar alive — success is already conveyed by the final answer + verified badge, and "已停止" (stopped)
// under a green badge reads as a contradiction. The bar's actionability and its exit-reason line must
// both gate on a "noteworthy" (non-success) exit reason, so only a genuine interruption surfaces one.
assert.ok(
  /SUCCESS_EXIT_REASONS[\s\S]*?"completed"[\s\S]*?"stop"/.test(runtimeSnapshotSrc),
  "RuntimeSnapshot must treat completed/stop as clean (non-actionable) completions",
);
assert.ok(
  /!noteworthyExitReason\(loop\.exit_reason\)/.test(runtimeSnapshotSrc),
  "a clean completion must not by itself keep the next-step bar actionable",
);
assert.ok(
  /noteworthyExitReason\(loop\.exit_reason\)\s*\?\s*`已停止:/.test(runtimeSnapshotSrc),
  "the '已停止: <reason>' line must only render for a noteworthy (non-success) exit reason",
);

console.log("session-main-path contract passed");
