// Single source of truth for the user-facing model-strategy vocabulary — the sibling of
// permissionTiers.ts, and deliberately the same shape.
//
// The ids below are NOT free-form: they must match the runtime CLI's `--model-strategy` choices
// (cli.py, `choices=["auto", "quality", "economy", "local"]`) byte for byte, because that string is
// what lib/run-flags.mjs hands to the runtime — as a flag on the cold path and as a JSON field on
// the warm one. A typo here does not fail loudly; argparse rejects the run, and the warm worker
// quietly falls back to "auto".
//
// Labels are plain language, no maintainer vocabulary (AGENTS.md §9).

export type ModelStrategyId = "auto" | "quality" | "economy" | "local";

export type ModelStrategy = {
  id: ModelStrategyId;
  label: string;
  hint: string;
  detail: string;
};

export const MODEL_STRATEGIES: ModelStrategy[] = [
  {
    id: "auto",
    label: "自动",
    hint: "按任务挑模型",
    detail: "运行时按每一步的难度、风险和预算自行挑选模型。多数情况下这就是最好的选择。",
  },
  {
    id: "quality",
    label: "重质量",
    hint: "偏向更强的模型",
    detail: "尽量用更强的模型，换取更好的结果。速度更慢、开销更大，适合难任务。",
  },
  {
    id: "economy",
    label: "重节省",
    hint: "偏向更省的模型",
    detail: "尽量用更便宜、更快的模型。适合大量简单改动，难任务上可能力有不逮。",
  },
  {
    id: "local",
    label: "本地优先",
    hint: "尽量用本地模型",
    detail: "尽量把工作交给本地模型，减少外发。取决于你本地配了哪些提供方。",
  },
];

export const DEFAULT_MODEL_STRATEGY: ModelStrategyId = "auto";

/** A settings value coerced to a strategy, falling back to the default. */
export function resolveModelStrategy(value: unknown): ModelStrategyId {
  return isModelStrategyId(value) ? value : DEFAULT_MODEL_STRATEGY;
}

export function isModelStrategyId(value: unknown): value is ModelStrategyId {
  return value === "auto" || value === "quality" || value === "economy" || value === "local";
}

export function modelStrategy(id: string | null | undefined): ModelStrategy {
  return MODEL_STRATEGIES.find((strategy) => strategy.id === id) ?? MODEL_STRATEGIES[0];
}
