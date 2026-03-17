import { invoke } from "@tauri-apps/api/core";

// OAuth
export async function startOAuth(
  provider: string,
  clientId: string,
  clientSecret: string,
  zohoRegion?: string
): Promise<void> {
  return invoke("start_oauth", { provider, clientId, clientSecret, zohoRegion });
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string | null;
  expires_in: number | null;
  token_type: string | null;
}

export async function exchangeOAuthCode(
  provider: string,
  code: string,
  clientId: string,
  clientSecret: string,
  zohoRegion?: string
): Promise<TokenResponse> {
  return invoke("exchange_oauth_code", { provider, code, clientId, clientSecret, zohoRegion });
}

// Sidecar
export interface SidecarResult {
  success: boolean;
  stdout: string;
  stderr: string;
}

export async function runPipeline(
  configPath: string,
  recordingPath: string
): Promise<SidecarResult> {
  return invoke("run_pipeline", { configPath, recordingPath });
}

export async function checkSidecarStatus(): Promise<boolean> {
  return invoke("check_sidecar_status");
}

// Diagnostics
export async function checkNvenc(): Promise<string> {
  return invoke("check_nvenc");
}

export async function checkFfmpeg(): Promise<boolean> {
  return invoke("check_ffmpeg");
}
