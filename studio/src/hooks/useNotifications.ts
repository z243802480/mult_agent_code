import { useEffect, useRef, useState } from "react";

// G1 通知体系 — the mainstream rule, verbatim: notify ONLY when something finished (or needs you)
// AND you are not looking (Claude Code fires OS notifications when "a session completes a task and
// you're not viewing that session"; Crush only notifies when the terminal is unfocused). The favicon
// carries an always-on status dot (Devin's green/orange favicon) so a glance at the tab strip reads
// the state without any notification at all.

const SETTING_KEY = "asteria.studio.notifications";

export function notificationsEnabled(): boolean {
  try {
    return localStorage.getItem(SETTING_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setNotificationsEnabled(on: boolean): void {
  try {
    localStorage.setItem(SETTING_KEY, on ? "on" : "off");
  } catch {
    // storage unavailable — the toggle simply won't persist
  }
}

export type NotificationPermissionState = "granted" | "denied" | "default" | "unsupported";

export function notificationPermission(): NotificationPermissionState {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission;
}

export async function requestNotificationPermission(): Promise<NotificationPermissionState> {
  if (typeof Notification === "undefined") return "unsupported";
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

function fire(title: string, body: string): void {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    const n = new Notification(title, { body, silent: true });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    // constructor can throw on some platforms (e.g. service-worker-only) — favicon dot still carries the state
  }
}

type RunSignals = {
  isRunning: boolean;
  waiting: boolean;
  interrupted: boolean;
  sessionTitle: string;
};

// Pure transition→notification decision (testable without a renderer). Returns null for "stay
// quiet"; the effect layers the enabled/hidden/permission gates on top.
export function notificationForTransition(
  was: { isRunning: boolean; waiting: boolean },
  now: RunSignals,
): { title: string; body: string } | null {
  if (!was.waiting && now.waiting) {
    return { title: "需要你的确认", body: `${now.sessionTitle} — 运行暂停，等待你的批准/决定。` };
  }
  if (was.isRunning && !now.isRunning && !now.waiting) {
    return now.interrupted
      ? {
          title: "运行已中断",
          body: `${now.sessionTitle} — 执行进程已不在了，回来看看发生了什么。`,
        }
      : { title: "任务已结束", body: `${now.sessionTitle} — 回来看看结果。` };
  }
  return null;
}

export function useNotifications(signals: RunSignals) {
  const { isRunning, waiting, interrupted, sessionTitle } = signals;
  const prev = useRef<{ isRunning: boolean; waiting: boolean } | null>(null);

  useEffect(() => {
    const was = prev.current;
    prev.current = { isRunning, waiting };
    // First observation is baseline, not a transition — never notify on mount/session switch.
    if (!was) return;
    if (!notificationsEnabled()) return;
    // The mainstream gate: only notify when the user is NOT looking at the page.
    if (!document.hidden) return;
    const decision = notificationForTransition(was, {
      isRunning,
      waiting,
      interrupted,
      sessionTitle,
    });
    if (decision) fire(decision.title, decision.body);
  }, [isRunning, waiting, interrupted, sessionTitle]);

  // Reset the baseline when the tracked session changes so a cross-session switch never reads as a
  // transition of the new session.
  useEffect(() => {
    prev.current = null;
  }, [sessionTitle]);

  useFaviconStatus(interrupted ? "failed" : waiting ? "waiting" : isRunning ? "running" : "idle");
}

// ── Favicon status dot ─────────────────────────────────────────────────────

type FaviconState = "idle" | "running" | "waiting" | "failed";

function tokenColor(name: string, fallback: string): string {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
}

function drawFavicon(state: FaviconState): string | null {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // Base glyph: accent rounded square + "A" (the app has no static favicon to overlay).
    ctx.beginPath();
    ctx.roundRect(1, 1, 30, 30, 8);
    ctx.fillStyle = tokenColor("--accent", "#4d9be6");
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 19px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("A", 16, 17);
    if (state !== "idle") {
      const dotColor =
        state === "waiting"
          ? tokenColor("--warn", "#d29922")
          : state === "failed"
            ? tokenColor("--bad", "#e5534b")
            : tokenColor("--ok", "#5fcf8e");
      ctx.beginPath();
      ctx.arc(24.5, 24.5, 6.5, 0, Math.PI * 2);
      ctx.fillStyle = dotColor;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();
    }
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

function useFaviconStatus(state: FaviconState) {
  const [link] = useState(() => {
    let el = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!el) {
      el = document.createElement("link");
      el.rel = "icon";
      document.head.appendChild(el);
    }
    return el;
  });
  useEffect(() => {
    const url = drawFavicon(state);
    if (url) link.href = url;
  }, [state, link]);
}
