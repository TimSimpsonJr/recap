/**
 * Read `_Recap/.recap/auth-token` with small retry.
 *
 * Needed because plugin-spawned daemons write the token AFTER the
 * plugin's initial onload read. The retry lets a fresh spawn's token
 * file appear without forcing a plugin reload.
 */
export interface VaultLike {
  exists: (path: string) => Promise<boolean>;
  read: (path: string) => Promise<string>;
}

export const AUTH_TOKEN_PATH = "_Recap/.recap/auth-token";

export async function readAuthTokenWithRetry(
  adapter: VaultLike,
  path: string = AUTH_TOKEN_PATH,
  maxAttempts: number = 3,
  delayMs: number = 500,
): Promise<string> {
  for (let i = 0; i < maxAttempts; i++) {
    if (await adapter.exists(path)) {
      const raw = await adapter.read(path);
      return raw.trim();
    }
    if (i < maxAttempts - 1) {
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  return "";
}
