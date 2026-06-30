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
    label: "Ask first",
    hint: "Asks before each edit and command",
    detail: "Every file edit and command waits for your approval. Safest and most hands-on.",
  },
  {
    id: "reviewed_auto",
    label: "Auto-edit",
    hint: "Edits apply directly; commands and risky steps still ask",
    detail:
      "File edits apply to your workspace as the agent works. Commands, and anything risky or irreversible, still pause for you.",
  },
  {
    id: "auto",
    label: "Full auto",
    hint: "Edits and tools apply; risky actions still interrupt",
    detail:
      "Edits and tool calls run with minimal prompting, for long, trusted tasks. Hard-stops, releases and destructive actions still interrupt.",
  },
];

export const DEFAULT_PERMISSION_TIER: PermissionTierId = "reviewed_auto";

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
