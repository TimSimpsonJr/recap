import { writable } from "svelte/store";
import { invoke } from "@tauri-apps/api/core";

export type ProviderName = "zoom" | "google" | "microsoft" | "zoho" | "todoist";
export type ConnectionStatus = "disconnected" | "connected" | "reconnect_required";

export interface ProviderState {
  clientId: string;
  clientSecret: string;
  accessToken: string | null;
  refreshToken: string | null;
  displayName: string | null;
  status: ConnectionStatus;
}

type CredentialsState = Record<ProviderName, ProviderState>;

const defaultProviderState: ProviderState = {
  clientId: "",
  clientSecret: "",
  accessToken: null,
  refreshToken: null,
  displayName: null,
  status: "disconnected",
};

const initialState: CredentialsState = {
  zoom: { ...defaultProviderState },
  google: { ...defaultProviderState },
  microsoft: { ...defaultProviderState },
  zoho: { ...defaultProviderState },
  todoist: { ...defaultProviderState },
};

export const credentials = writable<CredentialsState>(initialState);

async function storeValue(key: string, value: string): Promise<void> {
  await invoke("save_secret", { key, value });
}

async function getValue(key: string): Promise<string | null> {
  return invoke<string | null>("get_secret", { key });
}

async function removeValue(key: string): Promise<void> {
  await invoke("delete_secret", { key });
}

export async function loadCredentials(): Promise<void> {
  const providers: ProviderName[] = ["zoom", "google", "microsoft", "zoho", "todoist"];
  const state = { ...initialState };
  for (const provider of providers) {
    const clientId = await getValue(`${provider}.client_id`);
    const clientSecret = await getValue(`${provider}.client_secret`);
    const accessToken = await getValue(`${provider}.access_token`);
    const refreshToken = await getValue(`${provider}.refresh_token`);
    const displayName = await getValue(`${provider}.display_name`);
    state[provider] = {
      clientId: clientId ?? "",
      clientSecret: clientSecret ?? "",
      accessToken,
      refreshToken,
      displayName,
      status: accessToken ? "connected" : "disconnected",
    };
  }
  credentials.set(state);
}

export async function saveClientCredentials(
  provider: ProviderName,
  clientId: string,
  clientSecret: string
): Promise<void> {
  await storeValue(`${provider}.client_id`, clientId);
  await storeValue(`${provider}.client_secret`, clientSecret);
  credentials.update((state) => ({
    ...state,
    [provider]: { ...state[provider], clientId, clientSecret },
  }));
}

export async function saveTokens(
  provider: ProviderName,
  accessToken: string,
  refreshToken: string | null,
  displayName: string | null
): Promise<void> {
  await storeValue(`${provider}.access_token`, accessToken);
  if (refreshToken) await storeValue(`${provider}.refresh_token`, refreshToken);
  if (displayName) await storeValue(`${provider}.display_name`, displayName);
  credentials.update((state) => ({
    ...state,
    [provider]: { ...state[provider], accessToken, refreshToken, displayName, status: "connected" },
  }));
}

export async function disconnect(provider: ProviderName): Promise<void> {
  await removeValue(`${provider}.access_token`);
  await removeValue(`${provider}.refresh_token`);
  await removeValue(`${provider}.display_name`);
  credentials.update((state) => ({
    ...state,
    [provider]: { ...state[provider], accessToken: null, refreshToken: null, displayName: null, status: "disconnected" },
  }));
}

export async function saveHuggingFaceToken(token: string): Promise<void> {
  await storeValue("huggingface.token", token);
}

export async function getHuggingFaceToken(): Promise<string | null> {
  return getValue("huggingface.token");
}
