import { writable } from "svelte/store";
import { Client, Stronghold } from "@tauri-apps/plugin-stronghold";
import { appDataDir } from "@tauri-apps/api/path";

const VAULT_PASSWORD = "recap-vault-password";
const CLIENT_NAME = "recap";

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

let stronghold: Stronghold | null = null;
let store: any = null;

async function getStore() {
  if (store) return store;
  const dir = await appDataDir();
  stronghold = await Stronghold.load(`${dir}/vault.hold`, VAULT_PASSWORD);
  let client: Client;
  try {
    client = await stronghold.loadClient(CLIENT_NAME);
  } catch {
    client = await stronghold.createClient(CLIENT_NAME);
  }
  store = client.getStore();
  return store;
}

async function storeValue(key: string, value: string): Promise<void> {
  const s = await getStore();
  const data = Array.from(new TextEncoder().encode(value));
  await s.insert(key, data);
  await stronghold!.save();
}

async function getValue(key: string): Promise<string | null> {
  const s = await getStore();
  try {
    const data = await s.get(key);
    if (!data || data.length === 0) return null;
    return new TextDecoder().decode(new Uint8Array(data));
  } catch {
    return null;
  }
}

async function removeValue(key: string): Promise<void> {
  const s = await getStore();
  try {
    await s.remove(key);
    await stronghold!.save();
  } catch {
    // Key might not exist
  }
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
