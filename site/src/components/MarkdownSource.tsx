import { renderMarkdown } from "@/lib/markdown";
import { Markdown } from "./Markdown";

/** Server component: renders Markdown source at build time. */
export function MarkdownSource({
  source,
  className,
  handWritten,
}: {
  source: string;
  className?: string;
  handWritten?: boolean;
}) {
  return (
    <Markdown
      html={renderMarkdown(source)}
      {...(className ? { className } : {})}
      {...(handWritten !== undefined ? { handWritten } : {})}
    />
  );
}
