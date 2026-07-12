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
  return (
    <MarkdownErrorBoundary markdown={markdown}>
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
          {markdown}
        </ReactMarkdown>
      </article>
    </MarkdownErrorBoundary>
  );
}
