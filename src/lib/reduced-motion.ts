import { readable } from "svelte/store";

function getReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const reducedMotion = readable(getReducedMotion(), (set) => {
  if (typeof window === "undefined") return;
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  const handler = (e: MediaQueryListEvent) => set(e.matches);
  mql.addEventListener("change", handler);
  return () => mql.removeEventListener("change", handler);
});

/** Returns transition params with duration: 0 when reduced motion is preferred. */
export function motionParams<T extends { duration?: number }>(
  params: T,
  reduced: boolean
): T {
  if (reduced) return { ...params, duration: 0, delay: 0 };
  return params;
}
