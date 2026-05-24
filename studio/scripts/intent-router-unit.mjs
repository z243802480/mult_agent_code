import assert from "node:assert/strict";
import { chatPromptContract } from "../prompt-contract.mjs";
import { classifyChatRequest, intentAuditFor, routeUserIntent } from "../intent-router.mjs";

const cases = [
  {
    name: "ordinary question stays in chat",
    message: "How do I learn English effectively?",
    mode: "auto",
    permission: "ask",
    expected: { mode: "chat", intent_kind: "learning_plan", permission_effect: "read_only" },
  },
  {
    name: "content plan override is guarded to chat",
    message: "Plan a 3-day Qingdao travel itinerary",
    mode: "plan",
    permission: "ask",
    expected: { mode: "chat", intent_kind: "travel_plan", permission_effect: "read_only" },
  },
  {
    name: "workspace edit asks for plan under ask permission",
    message: "Fix the typo in README and run tests.",
    mode: "auto",
    permission: "ask",
    expected: { mode: "plan", intent_kind: "general", permission_effect: "read_only" },
  },
  {
    name: "workspace edit runs under allow permission",
    message: "Fix the typo in README and run tests.",
    mode: "auto",
    permission: "allow",
    expected: { mode: "run", intent_kind: "general", permission_effect: "execute_allowed" },
  },
  {
    name: "read-only repository analysis goes to plan",
    message: "Analyze this project architecture without changing files.",
    mode: "auto",
    permission: "ask",
    expected: { mode: "plan", intent_kind: "general", permission_effect: "read_only" },
  },
];

for (const item of cases) {
  const route = routeUserIntent(item.message, item.mode, item.permission);
  const audit = intentAuditFor(item.message, item.mode, item.permission, route);
  assert.equal(route.mode, item.expected.mode, `${item.name}: route mode`);
  assert.equal(audit.intent_kind, item.expected.intent_kind, `${item.name}: intent kind`);
  assert.equal(audit.permission_effect, item.expected.permission_effect, `${item.name}: permission effect`);
}

assert.equal(classifyChatRequest("设计一个青岛3天旅游计划"), "travel_plan");
assert.equal(classifyChatRequest("给我一个英语学习计划"), "learning_plan");
assert.equal(classifyChatRequest("写一个产品方案大纲"), "content_plan");

const contract = chatPromptContract().join("\n");
assert.match(contract, /Adapt the structure to the user request/);
assert.doesNotMatch(contract, /Qingdao|Laoshan|shadowing|audience/);

console.log("Studio intent router unit tests passed");
