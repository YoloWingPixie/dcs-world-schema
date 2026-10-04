/**
 * Markdown for hand-written overlays (content/**). Shared by the reference and
 * Lua API docs; build time and server components only (the client receives HTML).
 *
 *   parseFrontmatter(text, { file, allowed })  ->  { data, body }
 *   renderMarkdown(body)                        ->  HTML string (raw HTML escaped)
 *   markdownToText(body)                        ->  plain text for search indexes
 *
 * Render the HTML with components/Markdown.tsx (`<Markdown html={...} />`), or from a
 * server component with components/MarkdownSource.tsx (`<MarkdownSource source={...} />`).
 * Internal links are written site-relative (`/weapons/?id=AIM_120C`); the component
 * applies basePath and routes them client-side.
 */
import { Marked, type Tokens } from "marked";
import { parse as parseYaml } from "yaml";

export type Frontmatter = Record<string, unknown>;

export class FrontmatterError extends Error {}

const FENCE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

/**
 * Splits `---` YAML frontmatter from the body. With `allowed`, any other key throws a
 * FrontmatterError naming the file and the key.
 */
export function parseFrontmatter(
  text: string,
  opts: { file?: string; allowed?: readonly string[] } = {},
): { data: Frontmatter; body: string } {
  const match = FENCE.exec(text);
  if (!match) return { data: {}, body: text.trim() };
  let data: unknown;
  try {
    data = parseYaml(match[1] ?? "") ?? {};
  } catch (error) {
    throw new FrontmatterError(
      `${opts.file ?? "markdown"}: invalid frontmatter YAML: ${(error as Error).message}`,
    );
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new FrontmatterError(`${opts.file ?? "markdown"}: frontmatter must be a YAML mapping`);
  }
  if (opts.allowed) {
    const unknown = Object.keys(data).filter((k) => !opts.allowed?.includes(k));
    if (unknown.length) {
      throw new FrontmatterError(
        `${opts.file ?? "markdown"}: unknown frontmatter key${unknown.length > 1 ? "s" : ""} ` +
          `${unknown.map((k) => `"${k}"`).join(", ")} (allowed: ${opts.allowed.join(", ")})`,
      );
    }
  }
  return { data: data as Frontmatter, body: text.slice(match[0].length).trim() };
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const marked = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    // Overlays are prose: raw HTML is shown as text, never injected.
    html: (token: Tokens.HTML | Tokens.Tag) => escapeHtml(token.text),
    link(token: Tokens.Link) {
      const text = this.parser.parseInline(token.tokens);
      const external = /^[a-z]+:/i.test(token.href);
      const title = token.title ? ` title="${escapeHtml(token.title)}"` : "";
      const attrs = external ? ` rel="noopener noreferrer"` : ` data-internal=""`;
      return `<a href="${escapeHtml(token.href)}"${title}${attrs}>${text}</a>`;
    },
  },
});

export function renderMarkdown(source: string): string {
  return marked.parse(source, { async: false });
}

/** Plain text (for search and tooltips): markup and link targets dropped. */
export function markdownToText(source: string): string {
  return source
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[`*_>#~|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
