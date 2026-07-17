// How a Studio choice reaches the runtime — for BOTH ways a run can start.
//
// Studio has two spawn paths and they take their input in different shapes: the cold path builds a
// CLI command (so a choice travels as a flag), while the warm worker (ADR-0029 ②) reads a JSON
// request (so the same choice must travel as a field). Every user-facing run choice therefore needs
// a pair here, and both must derive from the SAME pure function on the SAME input — which is why
// they live in one module rather than two. Drift between the paths is silent, and it always errs
// toward the runtime's own default instead of the user's choice.
//
// Covers today: the permission tier (studio/src/permissionTiers.ts) and the model strategy
// (studio/src/modelStrategies.ts). Both vocabularies mirror the runtime CLI contract.

export function mapPermissionLevel(mode) {
  const normalized = String(mode || "").toLowerCase();
  if (normalized === "ask_everything" || normalized === "ask") return "ask";
  if (normalized === "auto") return "auto";
  // reviewed_auto / balanced / anything unknown -> the product default tier.
  return "balanced";
}

// Mirrors cli.py's `--model-strategy` choices (and studio/src/modelStrategies.ts). Exported so the
// settings endpoint can REJECT an unknown value at the door — the degrade-to-default below is for
// values already on disk, not for what a client is allowed to write.
export const MODEL_STRATEGY_IDS = ["auto", "quality", "economy", "local"];

// Mirrors models/routing.py MODEL_TIERS and the CLI's --model-name tier validation.
export const MODEL_TIERS = ["strong", "medium", "cheap"];

// An unknown value degrades to the same default argparse applies, so a stale or hand-edited
// settings.json can never make a run fail to start.
export function mapModelStrategy(strategy) {
  const normalized = String(strategy || "").toLowerCase();
  return MODEL_STRATEGY_IDS.includes(normalized) ? normalized : "auto";
}

// The warm worker takes a JSON request, not a CLI command, so it cannot read the flags spliced in
// below. It needs the same choices as DATA.
//
// Do NOT parse these values back out of the built command instead: that is a second source of truth,
// and dropping one is not a loud failure. For the tier it is a silent autonomy upgrade
// (studio_worker defaults to "balanced", so an "ask first" run would quietly get auto-repair,
// auto-replan and auto-accept); for the strategy it silently ignores what the user picked.
// See [[permission-mode-two-sources-of-truth]].
export function warmRunParams(mode, strategy, modelNames) {
  return {
    permission_level: mapPermissionLevel(mode),
    model_strategy: mapModelStrategy(strategy),
    model_name_overrides: mapModelNames(modelNames),
  };
}

export function withPermissionLevel(command, level) {
  return withRunFlag(command, "--permission-level", level);
}

export function withModelStrategy(command, strategy) {
  return withRunFlag(command, "--model-strategy", strategy);
}

// The CLI takes one `--model-name TIER=MODEL` per pinned tier, so this is the one run choice that is
// several flags rather than one. Built here in a single pass — `withRunFlag` refuses to add a flag
// the command already carries, so calling it once per tier would silently drop every tier after the
// first. Sorted so the command is stable across saves (an unstable command would make
// `sameCommand` warm-eligibility flap for no reason).
export function withModelNames(command, modelNames) {
  const names = mapModelNames(modelNames);
  const tiers = Object.keys(names).sort();
  if (!tiers.length || !Array.isArray(command)) return command;
  if (command.includes("--model-name")) return command;
  const runIndex = command.indexOf("run");
  if (runIndex < 0) return command;
  const flags = tiers.flatMap((tier) => ["--model-name", `${tier}=${names[tier]}`]);
  return [...command.slice(0, runIndex + 1), ...flags, ...command.slice(runIndex + 1)];
}

// Mirrors normalize_model_name_overrides in core/run_config.py: unknown tiers and blank values are
// dropped rather than rejected, so a stale settings.json can never stop a run from starting. The
// settings endpoint is where a bad value is refused — by the time it reaches here it is data, and
// data we cannot use is data we ignore.
export function mapModelNames(modelNames) {
  if (!modelNames || typeof modelNames !== "object") return {};
  const mapped = {};
  for (const [tier, name] of Object.entries(modelNames)) {
    const normalizedTier = String(tier || "").trim().toLowerCase();
    const normalizedName = String(name ?? "").trim();
    if (MODEL_TIERS.includes(normalizedTier) && normalizedName) {
      mapped[normalizedTier] = normalizedName;
    }
  }
  return mapped;
}

// Only the `run` subcommand (including `run --continue-session`) accepts these flags. Exact-token
// match on "run", so the module name (e.g. "asteria_runtime") never false-matches.
function withRunFlag(command, flag, value) {
  if (!value || !Array.isArray(command)) return command;
  if (command.includes(flag)) return command;
  const runIndex = command.indexOf("run");
  if (runIndex < 0) return command;
  return [...command.slice(0, runIndex + 1), flag, value, ...command.slice(runIndex + 1)];
}
