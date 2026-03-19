import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import {
  getRecorderState,
  startRecording,
  stopRecording,
  cancelRecording,
  type RecorderState,
} from "../tauri";

export const recorderState = writable<RecorderState>("idle");

/** Fetch current state from the backend and update the store. */
export async function refreshRecorderState(): Promise<void> {
  try {
    const state = await getRecorderState();
    recorderState.set(state);
  } catch (e) {
    console.error("Failed to get recorder state:", e);
  }
}

/** Start recording — delegates to IPC. */
export async function startRec(): Promise<void> {
  await startRecording();
}

/** Stop recording — delegates to IPC. */
export async function stopRec(): Promise<void> {
  await stopRecording();
}

/** Cancel recording — delegates to IPC. */
export async function cancelRec(): Promise<void> {
  await cancelRecording();
}

// Helper to extract the state tag from the discriminated union
export function recorderTag(state: RecorderState): string {
  if (typeof state === "string") return state;
  if ("armed" in state) return "armed";
  if ("detected" in state) return "detected";
  return "unknown";
}

/** Listen for recorder-state-changed events. */
let unlistenState: (() => void) | null = null;

export async function initRecorderListener(): Promise<void> {
  if (unlistenState) return;

  // Fetch initial state
  await refreshRecorderState();

  unlistenState = await listen<RecorderState>("recorder-state-changed", (event) => {
    recorderState.set(event.payload);
  });
}

export function destroyRecorderListener(): void {
  if (unlistenState) {
    unlistenState();
    unlistenState = null;
  }
}
