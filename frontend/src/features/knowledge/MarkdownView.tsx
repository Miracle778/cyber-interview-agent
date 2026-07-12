import { Component, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownViewProps {
  markdown: string;
}

interface MarkdownErrorBoundaryProps {
  markdown: string;
  children: ReactNode;
}

interface MarkdownErrorBoundaryState {
  hasError: boolean;
}

function stripYamlFrontmatter(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") return markdown;

  const closingIndex = lines.findIndex(
    (line, index) => index > 0 && line.trim() === "---",
  );
  if (closingIndex === -1) return markdown;

  return lines.slice(closingIndex + 1).join("\n").replace(/^\n/, "");
}

export class MarkdownErrorBoundary extends Component<
  MarkdownErrorBoundaryProps,
  MarkdownErrorBoundaryState
> {
  state: MarkdownErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): MarkdownErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="markdown-view markdown-view--fallback">
          {this.props.markdown}
        </pre>
      );
    }
    return this.props.children;
  }
}

export function MarkdownView({ markdown }: MarkdownViewProps) {
  const readableMarkdown = stripYamlFrontmatter(markdown);

  return (
    <MarkdownErrorBoundary markdown={readableMarkdown}>
      <article className="markdown-view">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children, ...props }) => {
              const external = Boolean(href && /^https?:\/\//i.test(href));
              return (
                <a
                  {...props}
                  href={href}
                  {...(external
                    ? { target: "_blank", rel: "noreferrer noopener" }
                    : {})}
                >
                  {children}
                </a>
              );
            },
          }}
        >
          {readableMarkdown}
        </ReactMarkdown>
      </article>
    </MarkdownErrorBoundary>
  );
}
