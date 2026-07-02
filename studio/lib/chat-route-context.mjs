/**
 * Build orchestration route input with recent chat context (S62-5).
 * State-machine only: if the main thread recently ended in chat without execute,
 * prepend conversation for strong re-route — not keyword NLU.
 */

/**
 * @param {Array<Record<string, unknown>>} events
 * @param {string} goal
 */
export function buildRouteMessageWithChatContext(events, goal) {
  const trimmedGoal = String(goal || "").trim();
  if (!trimmedGoal) return trimmedGoal;

  const context = recentChatContextForRoute(events);
  if (!context) return trimmedGoal;

  return [
    "Recent Studio chat (for strong orchestration routing only):",
    context,
    "",
    "Current user message:",
    trimmedGoal,
  ].join("\n");
}

/**
 * @param {Array<Record<string, unknown>>} events
 */
export function recentChatContextForRoute(events) {
  const mainEvents = (events || []).filter((event) => {
    const level = String(event?.display_level || "main");
    return level === "main" || !event?.display_level;
  });
  if (!mainEvents.length) return null;

  const lastExecuteIdx = findLastExecuteBoundaryIndex(mainEvents);
  const slice = mainEvents.slice(Math.max(0, lastExecuteIdx + 1));
  const turns = extractChatTurns(slice);
  if (!turns.length) return null;

  const lines = [];
  for (const turn of turns.slice(-3)) {
    if (turn.user) lines.push(`User: ${turn.user}`);
    if (turn.assistant) lines.push(`Assistant: ${turn.assistant}`);
  }
  return lines.length ? lines.join("\n") : null;
}

/**
 * Recent chat turns as [{role, content}] messages for injecting into ChatCommand history, so the
 * Studio chat is no longer single-turn amnesiac. Reuses the same turn extraction + execute-boundary
 * logic as routing, and keeps only COMPLETED (user+assistant) turns — the in-flight current question
 * (a trailing user-only turn) is dropped because the caller passes it separately as `question`.
 * @param {Array<Record<string, unknown>>} events
 * @param {number} maxTurns
 * @returns {Array<{ role: 'user' | 'assistant', content: string }>}
 */
export function recentChatHistoryMessages(events, maxTurns = 6) {
  const mainEvents = (events || []).filter((event) => {
    const level = String(event?.display_level || "main");
    return level === "main" || !event?.display_level;
  });
  if (!mainEvents.length) return [];

  const lastExecuteIdx = findLastExecuteBoundaryIndex(mainEvents);
  const slice = mainEvents.slice(Math.max(0, lastExecuteIdx + 1));
  const turns = extractChatTurns(slice).filter((turn) => turn.user && turn.assistant);
  const messages = [];
  for (const turn of turns.slice(-Math.max(0, maxTurns))) {
    messages.push({ role: "user", content: turn.user });
    messages.push({ role: "assistant", content: turn.assistant });
  }
  return messages;
}

/**
 * @param {Array<Record<string, unknown>>} events
 */
function findLastExecuteBoundaryIndex(events) {
  let boundary = -1;
  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    const type = String(event?.type || "");
    const phase = String(event?.phase || "");
    const routeMode = String(event?.intent_route?.mode || event?.intent_route?.studio_mode || "");

    if (type === "user_message" && ["execute", "plan", "understand", "resume", "review"].includes(phase)) {
      boundary = index;
      continue;
    }
    if (type === "intent_route" && ["run", "plan", "continue", "resume", "review", "accept"].includes(routeMode)) {
      boundary = index;
      continue;
    }
    if (type === "agent_turn" || (type === "tool_start" && phase === "execute")) {
      boundary = index;
    }
  }
  return boundary;
}

/**
 * @param {Array<Record<string, unknown>>} events
 */
function extractChatTurns(events) {
  /** @type {Array<{ user?: string, assistant?: string }>} */
  const turns = [];
  let pendingUser = null;

  for (const event of events) {
    const type = String(event?.type || "");
    const phase = String(event?.phase || "");
    if (type === "user_message" && (phase === "chat" || phase === "understand")) {
      pendingUser = clipText(String(event?.content_delta || event?.summary || ""), 400);
      continue;
    }
    if (type === "final_answer" && phase === "chat") {
      const assistant = clipText(String(event?.content_delta || event?.summary || ""), 600);
      if (pendingUser || assistant) {
        turns.push({ user: pendingUser || undefined, assistant: assistant || undefined });
        pendingUser = null;
      }
    }
  }

  if (pendingUser) turns.push({ user: pendingUser });
  return turns;
}

/**
 * @param {string} text
 * @param {number} max
 */
function clipText(text, max) {
  const compact = String(text || "").replace(/\s+/g, " ").trim();
  if (compact.length <= max) return compact;
  return `${compact.slice(0, max - 1)}…`;
}

/**
 * @param {Array<Record<string, unknown>>} events
 */
export function shouldAugmentRouteWithChatContext(events) {
  return Boolean(recentChatContextForRoute(events));
}
