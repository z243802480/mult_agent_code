import React from "react";

const EXAMPLE_PROMPTS = [
  "Find and fix the failing CI check",
  "Add a --version flag and a test for it",
  "Analyze the latest failure log and identify the root cause",
  "Turn these notes into a one-page PRD",
];

export function EmptyState({ onPrompt }: { onPrompt: (text: string) => void }) {
  return (
    <section className="emptyThread">
      <h2>What would you like to do?</h2>
      <p className="emptyHint">Ask, plan, or describe a goal — Asteria asks before sensitive actions.</p>
      <div className="examplePrompts">
        {EXAMPLE_PROMPTS.map((ex) => (
          <button key={ex} type="button" onClick={() => onPrompt(ex)}>{ex}</button>
        ))}
      </div>
    </section>
  );
}

