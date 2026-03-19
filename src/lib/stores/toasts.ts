import { writable } from "svelte/store";

export interface Toast {
  id: string;
  message: string;
  type: "success" | "error" | "info";
  duration?: number;
}

const { subscribe, update } = writable<Toast[]>([]);

export const toasts = { subscribe };

export function addToast(
  message: string,
  type: Toast["type"] = "info",
  duration = 4000
) {
  const id = crypto.randomUUID();
  update((t) => [...t, { id, message, type, duration }]);
  if (duration > 0) {
    setTimeout(() => removeToast(id), duration);
  }
  return id;
}

export function removeToast(id: string) {
  update((t) => t.filter((toast) => toast.id !== id));
}
