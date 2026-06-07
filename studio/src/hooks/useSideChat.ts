import { useCallback, useEffect, useState } from "react";

const STORAGE_OPEN = "asteria.studio.sideChatOpen";
const STORAGE_COMPOSER = "asteria.studio.composerSideAsk";

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function useSideChat() {
  const [open, setOpen] = useState(() => readFlag(STORAGE_OPEN));
  const [composerSideAsk, setComposerSideAsk] = useState(() => readFlag(STORAGE_COMPOSER));

  useEffect(() => {
    writeFlag(STORAGE_OPEN, open);
  }, [open]);

  useEffect(() => {
    writeFlag(STORAGE_COMPOSER, composerSideAsk);
  }, [composerSideAsk]);

  const toggle = useCallback(() => setOpen((value) => !value), []);
  const close = useCallback(() => setOpen(false), []);
  const toggleComposerSideAsk = useCallback(() => setComposerSideAsk((value) => !value), []);

  return {
    sideChatOpen: open,
    setSideChatOpen: setOpen,
    toggleSideChat: toggle,
    closeSideChat: close,
    composerSideAsk,
    setComposerSideAsk,
    toggleComposerSideAsk,
  };
}
