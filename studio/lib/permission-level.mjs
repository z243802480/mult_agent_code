// Maps the Studio permission-mode cycle (ask_everything / reviewed_auto / auto) to the runtime
// CLI's --permission-level value, and splices that flag into a `run` command so the user's chosen
// tier actually reaches the runtime. Without this the runtime always uses the CLI default
// (`balanced`), making the Studio permission control decorative.

export function mapPermissionLevel(mode) {
  const normalized = String(mode || "").toLowerCase();
  if (normalized === "ask_everything" || normalized === "ask") return "ask";
  if (normalized === "auto") return "auto";
  // reviewed_auto / balanced / anything unknown -> the product default tier.
  return "balanced";
}

// The warm worker (ADR-0029 ②) takes a JSON request, not a CLI command, so it cannot read the
// `--permission-level` flag `withPermissionLevel` splices in. It needs the same tier as DATA.
//
// Both paths derive from `mapPermissionLevel(mode)` — the same pure function on the same input — so
// they cannot disagree. Do NOT parse the level back out of the built command instead: that is a
// second source of truth, and dropping it is not a loud failure. It is a silent autonomy upgrade
// (studio_worker defaults to "balanced", so an "ask first" run would quietly get auto-repair,
// auto-replan and auto-accept). See [[permission-mode-two-sources-of-truth]].
export function warmRunParams(mode) {
  return { permission_level: mapPermissionLevel(mode) };
}

export function withPermissionLevel(command, level) {
  if (!level || !Array.isArray(command)) return command;
  if (command.includes("--permission-level")) return command;
  // Only the `run` subcommand (including `run --continue-session`) accepts and acts on the tier.
  // Exact-token match, so the module name (e.g. "asteria_runtime") never false-matches.
  const runIndex = command.indexOf("run");
  if (runIndex < 0) return command;
  return [
    ...command.slice(0, runIndex + 1),
    "--permission-level",
    level,
    ...command.slice(runIndex + 1),
  ];
}
