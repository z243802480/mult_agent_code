import { useSyncExternalStore } from "react";

// Lightweight global toast store. Any module can `import { toast } from "./toast"`
// and fire a confirmation without prop-threading; <ToastViewport/> subscribes once.
// Mirrors the established inline-confirmation pattern (ClampedOutput "Copied",
// PermissionCard resolved) for fire-and-forget actions that remove their own button.

export type ToastTone = "success" | "error" | "info";

export type ToastAction = { label: string; onClick: () => void };

export type Toast = {
  id: number;
  message: string;
  tone: ToastTone;
  action?: ToastAction;
  duration: number;
};

type ToastOptions = { action?: ToastAction; duration?: number };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function pushToast(
  message: string,
  opts: { tone?: ToastTone } & ToastOptions = {},
): number {
  const id = nextId++;
  toasts = [
    ...toasts,
    {
      id,
      message,
      tone: opts.tone ?? "info",
      action: opts.action,
      duration: opts.duration ?? 4000,
    },
  ];
  emit();
  return id;
}

export function dismissToast(id: number): void {
  const next = toasts.filter((item) => item.id !== id);
  if (next.length !== toasts.length) {
    toasts = next;
    emit();
  }
}

export const toast = {
  success: (message: string, opts?: ToastOptions) => pushToast(message, { ...opts, tone: "success" }),
  error: (message: string, opts?: ToastOptions) => pushToast(message, { ...opts, tone: "error" }),
  info: (message: string, opts?: ToastOptions) => pushToast(message, { ...opts, tone: "info" }),
};

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Toast[] {
  return toasts;
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
