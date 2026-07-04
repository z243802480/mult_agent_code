import React, { useEffect, useMemo, useRef, useState } from "react";

export type Command = { id: string; label: string; hint?: string; run: () => void };

// Ctrl/Cmd+K command palette (I13): fuzzy-ish filter over sessions + actions, full keyboard control.
// Every action maps to an existing handler — the palette is a fast entry point, not new behavior.
export function CommandPalette({ open, commands, onClose }: { open: boolean; commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const prevFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    // Remember what was focused so we can restore it on close (don't strand keyboard focus).
    prevFocus.current = document.activeElement as HTMLElement | null;
    setQuery("");
    setActive(0);
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => {
      cancelAnimationFrame(id);
      prevFocus.current?.focus?.();
    };
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) => c.label.toLowerCase().includes(q) || (c.hint ?? "").toLowerCase().includes(q),
    );
  }, [query, commands]);

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  if (!open) return null;

  const run = (cmd?: Command) => {
    if (!cmd) return;
    onClose();
    cmd.run();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); return; }
    if (e.key === "Enter") { e.preventDefault(); run(filtered[active]); return; }
    // Focus trap: the input is the only tab stop in this aria-modal dialog, so swallow Tab to keep
    // keyboard focus inside the palette instead of letting it escape to the background thread.
    if (e.key === "Tab") { e.preventDefault(); return; }
  };

  const activeId = filtered.length ? `cmdkopt-${active}` : undefined;

  return (
    <div className="cmdkOverlay" onClick={onClose}>
      <div className="cmdkPanel" role="dialog" aria-modal="true" aria-label="Command palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmdkInput"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a command or session…"
          aria-label="Command palette search"
          role="combobox"
          aria-expanded
          aria-controls="cmdkList"
          aria-activedescendant={activeId}
        />
        <ul className="cmdkList" id="cmdkList" role="listbox" aria-label="Commands">
          {filtered.length === 0 && <li className="cmdkEmpty">No matches</li>}
          {filtered.map((cmd, i) => (
            <li
              key={cmd.id}
              id={`cmdkopt-${i}`}
              role="option"
              aria-selected={i === active}
              className={`cmdkItem ${i === active ? "active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => run(cmd)}
            >
              <span className="cmdkItemLabel">{cmd.label}</span>
              {cmd.hint && <span className="cmdkItemHint">{cmd.hint}</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
