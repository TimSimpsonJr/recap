import { marked } from "marked";
import { assetUrl } from "./assets";

/**
 * Pre-process Obsidian-specific syntax before passing to marked:
 * - ![[image.png]] → standard markdown image with asset URL
 * - [[link|display]] → HTML span with wikilink class
 * - [[link]] → HTML span with wikilink class
 */
function preprocessObsidian(
  md: string,
  transformPath?: (path: string) => string
): string {
  const resolve = transformPath ?? ((p: string) => p);

  // Image embeds: ![[filename.ext]]
  let result = md.replace(
    /!\[\[([^\]]+)\]\]/g,
    (_match, filename: string) => {
      const src = resolve(filename.trim());
      return `![${filename.trim()}](${src})`;
    }
  );

  // Wikilinks with display text: [[target|display]]
  result = result.replace(
    /\[\[([^|\]]+)\|([^\]]+)\]\]/g,
    (_match, target: string, display: string) => {
      const name = display.trim();
      const href = `#filter/participant/${encodeURIComponent(target.trim())}`;
      return `<a class="wikilink" href="${href}">${name}</a>`;
    }
  );

  // Plain wikilinks: [[target]]
  result = result.replace(
    /\[\[([^\]]+)\]\]/g,
    (_match, target: string) => {
      const name = target.trim();
      const href = `#filter/participant/${encodeURIComponent(name)}`;
      return `<a class="wikilink" href="${href}">${name}</a>`;
    }
  );

  return result;
}

/**
 * Render markdown to HTML, handling Obsidian wikilink and image embed syntax.
 *
 * @param md - Raw markdown string (may contain Obsidian syntax)
 * @param options.transformImagePath - Optional function to resolve image paths
 *   (defaults to assetUrl for Tauri file:// protocol conversion)
 */
export function renderMarkdown(
  md: string,
  options?: { transformImagePath?: (path: string) => string }
): string {
  const transformPath = options?.transformImagePath ?? assetUrl;
  const preprocessed = preprocessObsidian(md, transformPath);
  return marked.parse(preprocessed) as string;
}
