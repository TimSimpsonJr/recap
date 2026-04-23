/**
 * Resolve a vault-relative path to the concrete filesystem path.
 *
 * Obsidian's FileSystemAdapter (desktop) exposes an internal
 * `getFullPath(vaultRelative)` method that returns the OS-absolute
 * path. The method is undocumented but stable across versions we
 * support. Non-FileSystem adapters (mobile, web) don't have it — we
 * fall back to the input path unchanged, which is degraded but
 * non-crashing (the launcher state machine already tolerates an
 * empty log-path env var).
 */
export function vaultRelativeToConcrete(
  adapter: unknown,
  vaultRelative: string,
): string {
  const getFullPath = (adapter as { getFullPath?: (p: string) => string })
    .getFullPath;
  if (typeof getFullPath === "function") {
    try {
      return getFullPath.call(adapter, vaultRelative);
    } catch {
      // Fall through to return the relative path.
    }
  }
  return vaultRelative;
}
