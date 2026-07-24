function displayValue(value: unknown) {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : null;
}

export function formatEvidenceLocator(locator: Record<string, unknown>) {
  const pieces: string[] = [];
  const position = formatEvidencePosition(locator);
  if (position) pieces.push(position);

  for (const key of ["section", "heading", "block", "title"]) {
    const value = displayValue(locator[key]);
    if (value && !pieces.includes(value)) {
      pieces.push(value);
      break;
    }
  }
  return pieces.join(" · ") || "简历中的位置";
}

export function formatEvidencePosition(locator: Record<string, unknown>) {
  const page = displayValue(locator.page);
  const paragraph = displayValue(locator.paragraph);
  const paragraphStart = displayValue(locator.paragraphStart);
  const paragraphEnd = displayValue(locator.paragraphEnd);
  const lineStart = displayValue(locator.lineStart);
  const lineEnd = displayValue(locator.lineEnd);

  if (page) return `第 ${page} 页`;
  if (paragraph) return `第 ${paragraph} 段`;
  if (paragraphStart && paragraphEnd) {
    return paragraphStart === paragraphEnd
      ? `第 ${paragraphStart} 段`
      : `第 ${paragraphStart}–${paragraphEnd} 段`;
  }
  if (paragraphStart) return `第 ${paragraphStart} 段`;
  if (lineStart && lineEnd) {
    return lineStart === lineEnd
      ? `第 ${lineStart} 行`
      : `第 ${lineStart}–${lineEnd} 行`;
  }
  if (lineStart) return `第 ${lineStart} 行`;
  return "";
}

export function formatEvidenceTitle(locator: Record<string, unknown>) {
  for (const key of ["block", "title", "heading", "section"]) {
    const value = displayValue(locator[key]);
    if (value) return value;
  }
  const page = displayValue(locator.page);
  const paragraph = displayValue(locator.paragraph)
    ?? displayValue(locator.paragraphStart);
  const lineStart = displayValue(locator.lineStart);
  const lineEnd = displayValue(locator.lineEnd);

  if (page) return `第 ${page} 页内容`;
  if (paragraph) return `第 ${paragraph} 段内容`;
  if (lineStart && lineEnd) {
    return lineStart === lineEnd
      ? `第 ${lineStart} 行内容`
      : `第 ${lineStart}–${lineEnd} 行内容`;
  }
  if (lineStart) return `第 ${lineStart} 行内容`;
  return "简历内容";
}
