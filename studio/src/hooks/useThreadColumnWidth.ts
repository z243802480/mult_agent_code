import React from "react";

const THREAD_MIN = 480;
const THREAD_MAX = 920;
const THREAD_GUTTER = 40;

export function useThreadColumnWidth(containerRef: React.RefObject<HTMLElement | null>) {
  const [threadMax, setThreadMax] = React.useState(860);

  React.useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    function update(width: number) {
      const next = Math.round(Math.min(THREAD_MAX, Math.max(THREAD_MIN, width - THREAD_GUTTER)));
      setThreadMax((prev) => (prev === next ? prev : next));
    }

    update(element.clientWidth);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      update(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [containerRef]);

  return threadMax;
}
