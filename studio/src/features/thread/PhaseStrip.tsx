import React from "react";
import { MACRO_PHASES, macroPhase } from "./planModel";

// A single quiet inline row mapping the run's current phase onto understand→plan→execute→review→done.
// Only segments actually reached are lit; the active one pulses while running. Honest: renders nothing
// when there is no recognizable phase (never invents a stage the run has not entered).
export function PhaseStrip({ phase, running }: { phase?: string; running: boolean }) {
  const current = macroPhase(phase);
  const idx = MACRO_PHASES.findIndex((p) => p.key === current);
  if (idx < 0) return null;
  return (
    <div className="phaseStrip" role="progressbar" aria-valuenow={idx + 1} aria-valuemin={1} aria-valuemax={MACRO_PHASES.length}>
      {MACRO_PHASES.map((p, i) => {
        const state = i < idx ? "done" : i === idx ? (running ? "active" : "done") : "todo";
        return (
          <span key={p.key} className={`phaseSeg ${state}`}>
            <span className="phaseSegDot" />
            <span className="phaseSegLabel">{p.label}</span>
          </span>
        );
      })}
    </div>
  );
}
