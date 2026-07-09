import assert from "node:assert/strict";
import {
  buildRouteMessageWithChatContext,
  recentChatContextForRoute,
  shouldAugmentRouteWithChatContext,
} from "../lib/chat-route-context.mjs";

const chatEvents = [
  {
    type: "user_message",
    phase: "chat",
    display_level: "main",
    content_delta: "greet_cli 现在怎么工作的？",
  },
  {
    type: "final_answer",
    phase: "chat",
    display_level: "main",
    content_delta: "greet_cli 是一个简单 CLI，读取参数后打印问候语。",
  },
];

assert.equal(shouldAugmentRouteWithChatContext(chatEvents), true);
assert.match(
  buildRouteMessageWithChatContext(chatEvents, "那就改吧，加上 --version"),
  /Recent Studio chat/,
);
assert.match(buildRouteMessageWithChatContext(chatEvents, "那就改吧，加上 --version"), /greet_cli/);

const afterExecute = [
  ...chatEvents,
  {
    type: "intent_route",
    display_level: "inspector",
    intent_route: { mode: "run" },
  },
  {
    type: "user_message",
    phase: "execute",
    display_level: "main",
    content_delta: "给 greet_cli 增加 --version",
  },
];

assert.equal(recentChatContextForRoute(afterExecute), null);
assert.equal(buildRouteMessageWithChatContext(afterExecute, "继续"), "继续");

console.log("chat-execute-handoff-smoke: ok");
