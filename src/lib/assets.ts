import { convertFileSrc } from "@tauri-apps/api/core";

export function assetUrl(path: string): string {
  return convertFileSrc(path);
}
