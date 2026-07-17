// Single source of truth for the user-facing permission/autonomy vocabulary.
//
// Before this, three layers disagreed (a dead "ask-for-write" string in the settings endpoint,
// the Composer's local labels, and the runtime mapping). The canonical tier ids below are the
// ones Composer, the Settings panel, server.mjs (PERMISSION_TIER_IDS), permission-level.mjs and
// the runtime's permission_policy.py all agree on. Each id maps to a runtime --permission-level:
//   ask_everything -> ask | reviewed_auto -> balanced | auto -> auto
//
// Labels are short enough for the composer's segmented control; `detail` is the plain-language
// sentence shown in the Settings panel. No maintainer vocabulary (AGENTS.md §9); strings English.

export type PermissionTierId = "ask_everything" | "reviewed_auto" | "auto";

export type PermissionTier = {
  id: PermissionTierId;
  label: string;
  hint: string;
  detail: string;
};

export const PERMISSION_TIERS: PermissionTier[] = [
  {
    id: "ask_everything",
    label: "逐步询问",
    hint: "每次编辑和命令前都会询问",
    detail: "每次文件编辑和命令都会等待你的批准。最安全、最贴身。",
  },
  {
    id: "reviewed_auto",
    label: "自动编辑",
    hint: "编辑直接应用；有风险的命令和不可逆操作仍会询问",
    detail:
      "文件编辑会随 agent 工作直接应用到你的工作区。有风险或不可逆的操作（破坏性、联网、密钥、发布类命令）仍会为你暂停；普通命令直接运行。",
  },
  {
    id: "auto",
    label: "全自动",
    hint: "编辑和工具直接执行；有风险的操作仍会中断",
    detail:
      "编辑和工具调用以最少的询问运行，适合长时间、可信赖的任务。硬停止、发布和破坏性操作仍会中断。",
  },
];

export const DEFAULT_PERMISSION_TIER: PermissionTierId = "reviewed_auto";

/**
 * A settings value coerced to a tier, falling back to the default.
 *
 * The `isPermissionTierId(x) ? x : DEFAULT_PERMISSION_TIER` dance was written out at two call sites
 * in App.tsx. Which tier an unrecognised value degrades to is a safety decision — it belongs in one
 * place, not copied wherever a tier is read.
 */
export function resolvePermissionTier(value: unknown): PermissionTierId {
  return isPermissionTierId(value) ? value : DEFAULT_PERMISSION_TIER;
}

export function isPermissionTierId(value: unknown): value is PermissionTierId {
  return value === "ask_everything" || value === "reviewed_auto" || value === "auto";
}

export function permissionTier(id: string | null | undefined): PermissionTier {
  return PERMISSION_TIERS.find((tier) => tier.id === id) ?? PERMISSION_TIERS[1];
}

// Legacy "ask"|"allow" flag still expected by the goal-submit payload. Only the strictest tier
// asks up-front for edits; the other two auto-apply edits (commands still prompt server-side).
export function legacyPermission(id: PermissionTierId): "ask" | "allow" {
  return id === "ask_everything" ? "ask" : "allow";
}
