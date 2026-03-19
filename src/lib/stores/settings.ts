import { writable } from "svelte/store";
import { Store } from "@tauri-apps/plugin-store";

export interface AppSettings {
  vaultPath: string;
  meetingsFolder: string;
  peopleFolder: string;
  companiesFolder: string;
  recordingsFolder: string;
  whisperxModel: string;
  whisperxDevice: string;
  whisperxComputeType: string;
  whisperxLanguage: string;
  todoistProject: string;
  todoistLabels: string;
  zohoRegion: string;
  showNotificationOnComplete: boolean;
  autoDetectMeetings: boolean;
  detectionAction: "ask" | "always_record" | "never_record";
  timeoutAction: "record" | "skip";
  notificationTimeoutSeconds: number;
  zoomLevel: number;
  meetingNotifications: boolean;
  meetingLeadTimeMinutes: number;
  screenShareMonitor: number;
  autoRecordAllCalendar: boolean;
}

const defaults: AppSettings = {
  vaultPath: "",
  meetingsFolder: "Work/Meetings",
  peopleFolder: "Work/People",
  companiesFolder: "Work/Companies",
  recordingsFolder: "",
  whisperxModel: "large-v3",
  whisperxDevice: "cuda",
  whisperxComputeType: "float16",
  whisperxLanguage: "en",
  todoistProject: "",
  todoistLabels: "",
  zohoRegion: "com",
  showNotificationOnComplete: true,
  autoDetectMeetings: true,
  detectionAction: "ask",
  timeoutAction: "record",
  notificationTimeoutSeconds: 60,
  zoomLevel: 1.0,
  meetingNotifications: true,
  meetingLeadTimeMinutes: 10,
  screenShareMonitor: 0,
  autoRecordAllCalendar: false,
};

export const settings = writable<AppSettings>({ ...defaults });

let tauriStore: Store | null = null;

async function getStore(): Promise<Store> {
  if (!tauriStore) {
    tauriStore = await Store.load("settings.json");
  }
  return tauriStore;
}

export async function loadSettings(): Promise<void> {
  const store = await getStore();
  const loaded: Partial<AppSettings> = {};
  for (const [key, defaultValue] of Object.entries(defaults)) {
    const value = await store.get(key);
    if (value !== null && value !== undefined) {
      (loaded as any)[key] = value;
    } else {
      (loaded as any)[key] = defaultValue;
    }
  }
  settings.set(loaded as AppSettings);
}

export async function saveSetting<K extends keyof AppSettings>(
  key: K,
  value: AppSettings[K]
): Promise<void> {
  const store = await getStore();
  await store.set(key, value);
  await store.save();
  settings.update((s) => ({ ...s, [key]: value }));
}

export async function saveAllSettings(values: AppSettings): Promise<void> {
  const store = await getStore();
  for (const [key, value] of Object.entries(values)) {
    await store.set(key, value);
  }
  await store.save();
  settings.set(values);
}
