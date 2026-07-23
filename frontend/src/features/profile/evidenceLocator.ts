function displayValue(value: unknown) {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : null;
}

export function formatEvidenceLocator(locator: Record<string, unknown>) {
  const pieces: string[] = [];
  const page = displayValue(locator.page);
  const paragraph = displayValue(locator.paragraph);
  const lineStart = displayValue(locator.lineStart);
  const lineEnd = displayValue(locator.lineEnd);

  if (page) pieces.push(`第 ${page} 页`);
  else if (paragraph) pieces.push(`第 ${paragraph} 段`);
  else if (lineStart && lineEnd) {
    pieces.push(lineStart === lineEnd
      ? `第 ${lineStart} 行`
      : `第 ${lineStart}–${lineEnd} 行`);
  } else if (lineStart) pieces.push(`第 ${lineStart} 行`);

  for (const key of ["section", "heading", "block", "title"]) {
    const value = displayValue(locator[key]);
    if (value && !pieces.includes(value)) {
      pieces.push(value);
      break;
    }
  }
  return pieces.join(" · ") || "材料证据";
}
