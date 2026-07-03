import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

// A <pre> with a hover-revealed copy button — for raw JSON / command output in the Inspector, where
// users routinely need to grab a payload without hand-selecting. Clipboard failure is a silent no-op.
export function CopyablePre({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (headless / insecure context) */
    }
  }
  return (
    <div className="copyablePre">
      <button
        type="button"
        className="copyablePreBtn"
        title="Copy"
        aria-label="Copy"
        onClick={() => void copy()}
      >
        {copied ? <Check size={11} /> : <Copy size={11} />}
      </button>
      <pre className={className}>{text}</pre>
    </div>
  );
}
