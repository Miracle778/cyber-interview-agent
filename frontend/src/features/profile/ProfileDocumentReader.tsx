import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Download, FileText, List, LockKeyhole, ShieldCheck, X } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ProfileDocumentOutlineItem, ProfileMaterialDocument } from "./profileTypes";

function lineRange(item: ProfileDocumentOutlineItem) {
  const start = Number(item.locator.lineStart ?? item.locator.line_start ?? 0);
  const end = Number(item.locator.lineEnd ?? item.locator.line_end ?? start);
  return { start: Number.isFinite(start) ? start : 0, end: Number.isFinite(end) ? end : start };
}

function formatInline(text: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)]+\))/g;
  return text.split(pattern).filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/.exec(part);
    if (link) {
      return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    }
    return part;
  });
}

function cleanOutlineTitle(item: ProfileDocumentOutlineItem, lines: string[], headingTitles: Set<string>) {
  const { start } = lineRange(item);
  const sourceLine = start > 0 ? lines[start - 1]?.trim() ?? "" : "";
  const markdownHeading = /^#{1,6}\s+(.+)$/.exec(sourceLine)?.[1];
  const boldHeading = /^(?:\*\*|__)(.+?)(?:\*\*|__)\s*$/.exec(sourceLine)?.[1];
  const candidate = (markdownHeading ?? boldHeading ?? item.title)
    .replace(/^#{1,6}\s*/, "")
    .replace(/^(?:\*\*|__)|(?:\*\*|__)$/g, "")
    .trim();
  if (headingTitles.size > 0 && !headingTitles.has(candidate)) return null;
  if (!candidate || candidate.length > 36 || /[。！？；：]\s*\S/.test(candidate)) return null;
  return candidate;
}

function displayLine(line: string, lineNumber: number, focused: boolean) {
  const heading = /^(#{1,6})\s+(.+)$/.exec(line);
  const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
  if (!line.trim()) return <div key={lineNumber} data-line={lineNumber} className="profile-document-reader__blank" />;
  if (heading) return <h3 key={lineNumber} data-line={lineNumber} data-level={heading[1].length} data-focused={focused || undefined}>{formatInline(heading[2])}</h3>;
  if (bullet) return <p key={lineNumber} data-line={lineNumber} data-focused={focused || undefined} className="profile-document-reader__bullet">{formatInline(bullet[1])}</p>;
  return <p key={lineNumber} data-line={lineNumber} data-focused={focused || undefined}>{formatInline(line)}</p>;
}

export function ProfileDocumentReader({
  document,
  focusEvidenceId,
  downloadUrl,
  onBack,
}: {
  document: ProfileMaterialDocument;
  focusEvidenceId?: string;
  downloadUrl: string;
  onBack: () => void;
}) {
  const [view, setView] = useState<"original" | "redacted">("original");
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [focusedId, setFocusedId] = useState(focusEvidenceId ?? document.outline[0]?.evidenceId ?? "");
  const bodyRef = useRef<HTMLElement>(null);
  const focusedItem = document.outline.find((item) => item.evidenceId === focusedId) ?? null;
  const focusedRange = focusedItem ? lineRange(focusedItem) : { start: 0, end: 0 };
  const lines = useMemo(() => (view === "original" ? document.originalText : document.redactedText).split("\n"), [document, view]);
  const outline = useMemo(() => {
    const headingTitles = new Set(lines.flatMap((line) => {
      const trimmed = line.trim();
      const title = /^#{1,6}\s+(.+)$/.exec(trimmed)?.[1]
        ?? /^(?:\*\*|__)(.+?)(?:\*\*|__)\s*$/.exec(trimmed)?.[1];
      return title ? [title.trim()] : [];
    }));
    const seen = new Set<string>();
    return document.outline.flatMap((item) => {
      const title = cleanOutlineTitle(item, lines, headingTitles);
      if (!title || seen.has(title)) return [];
      seen.add(title);
      return [{ item, title }];
    });
  }, [document.outline, lines]);

  useEffect(() => {
    if (!focusedRange.start) return;
    bodyRef.current?.querySelector(`[data-line="${focusedRange.start}"]`)?.scrollIntoView({ block: "center" });
  }, [focusedId, focusedRange.start, view]);

  function focus(item: ProfileDocumentOutlineItem) {
    setFocusedId(item.evidenceId);
    setDirectoryOpen(false);
    const range = lineRange(item);
    if (range.start) bodyRef.current?.querySelector(`[data-line="${range.start}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  return <section className="profile-document-reader" aria-labelledby="profile-document-title">
    <header>
      <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft size={16} />返回</Button>
      <FileText size={22} />
      <div><h2 id="profile-document-title">{document.fileName}</h2><p>第 {document.versionNumber} 版 · 完整简历阅读</p></div>
      <div className="profile-document-reader__view" role="group" aria-label="简历内容版本">
        <button type="button" aria-pressed={view === "original"} onClick={() => setView("original")}><LockKeyhole size={14} />本地原文</button>
        <button type="button" aria-pressed={view === "redacted"} onClick={() => setView("redacted")}><ShieldCheck size={14} />模型脱敏版</button>
      </div>
      <Button className="profile-document-reader__directory-toggle" variant="secondary" size="sm" onClick={() => setDirectoryOpen(true)}><List size={16} />目录</Button>
      <a className="profile-document-reader__download" href={downloadUrl}><Download size={16} />下载原文件</a>
    </header>
    <div className="profile-document-reader__layout">
      <aside aria-label="简历目录" data-open={directoryOpen || undefined}>
        <button className="profile-document-reader__directory-close" type="button" aria-label="关闭目录" onClick={() => setDirectoryOpen(false)}><X size={18} /></button>
        <strong>内容目录</strong>
        <p>点击可定位到对应原文。</p>
        <nav>{outline.map(({ item, title }) => <button key={item.evidenceId} type="button" aria-current={focusedId === item.evidenceId} onClick={() => focus(item)}>{title}</button>)}</nav>
      </aside>
      {directoryOpen ? <button className="profile-document-reader__directory-backdrop" type="button" aria-label="关闭目录" onClick={() => setDirectoryOpen(false)} /> : null}
      <article ref={bodyRef}>
        <div className="profile-document-reader__privacy"><LockKeyhole size={15} /><span>{view === "original" ? "本地原文仅在当前工作区显示，不会发送给模型。" : "这是画像助手实际可读取的脱敏内容。"}</span></div>
        <div className="profile-document-reader__paper">
          {lines.map((line, index) => displayLine(line, index + 1, focusedRange.start > 0 && index + 1 >= focusedRange.start && index + 1 <= focusedRange.end))}
        </div>
      </article>
    </div>
  </section>;
}
