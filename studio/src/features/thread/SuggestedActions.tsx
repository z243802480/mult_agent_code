import React, { useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import type { NarrativeStep as NarrativeStepType } from "../../types";

type SuggestedAction = { kind: string; label: string; command: string };

/**
 * Inline suggested-action chips (slice #6): the runtime attaches contextual follow-ups
 * (`event.actions` = {kind,label,command}) to events — e.g. "Check connection" / "Retry run"
 * / "Decide". They were never rendered. Here they follow the relevant turn's final answer
 * (not a fixed top bar), so the next step sits where the user just read the result.
 *
 * Only the latest turn renders them: these are next-step suggestions, so showing them on
 * historical turns would be stale. Clicking dispatches the same runtime command path the
 * snapshot buttons use — no fabricated actions, only what the runtime suggested.
 */
export function SuggestedActions({
  steps,
  onAction,
}: {
  steps: NarrativeStepType[];
  onAction: (command: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const seen = new Set<string>();
  const actions: SuggestedAction[] = [];
  for (const step of steps) {
    for (const event of step.events) {
      for (const raw of event.actions ?? []) {
        const command = String((raw as SuggestedAction).command ?? "").trim();
        const label = String((raw as SuggestedAction).label ?? "").trim();
        if (!command || !label || seen.has(command)) continue;
        seen.add(command);
        actions.push({ kind: String((raw as SuggestedAction).kind ?? ""), label, command });
      }
    }
  }
  if (!actions.length) return null;

  async function run(command: string) {
    setBusy(command);
    try {
      await onAction(command);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="suggestedActions" aria-label="建议的后续操作">
      {actions.map((action) => (
        <button
          key={action.command}
          type="button"
          className="suggestedActionChip"
          disabled={Boolean(busy)}
          onClick={() => void run(action.command)}
        >
          {busy === action.command ? (
            <Loader2 size={12} className="spinning" />
          ) : (
            <ArrowRight size={12} />
          )}
          <span>{action.label}</span>
        </button>
      ))}
    </div>
  );
}
