import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useState } from "react";

export function SourceFileCard({ filename, content }: { filename: string; content: string }) {
  const [expanded, setExpanded] = useState(false);
  const lineCount = content.split("\n").length;
  return (
    <div className="source-file-card">
      <button type="button" className="source-file-card__toggle" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <FileText size={15} />
        <span className="source-file-card__name">{filename}</span>
        <small className="source-file-card__meta">{lineCount} 行 · 点击{expanded ? "收起" : "展开"}原文</small>
      </button>
      {expanded ? <pre className="source-file-card__content">{content}</pre> : null}
    </div>
  );
}
