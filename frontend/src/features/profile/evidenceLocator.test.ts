import { describe, expect, it } from "vitest";
import {
  formatEvidenceLocator,
  formatEvidencePosition,
  formatEvidenceTitle,
} from "./evidenceLocator";

describe("evidence locator presentation", () => {
  it("uses a semantic block title when the parser provides one", () => {
    const locator = {
      lineStart: 8,
      lineEnd: 12,
      section: "项目经历",
      block: "Cyber Interview Agent",
    };

    expect(formatEvidenceTitle(locator)).toBe("Cyber Interview Agent");
    expect(formatEvidencePosition(locator)).toBe("第 8–12 行");
    expect(formatEvidenceLocator(locator)).toBe("第 8–12 行 · 项目经历");
  });

  it("gives old evidence a distinguishable title instead of a generic fragment label", () => {
    expect(formatEvidenceTitle({ page: 2 })).toBe("第 2 页内容");
    expect(formatEvidenceTitle({ paragraph: 6 })).toBe("第 6 段内容");
    expect(formatEvidenceTitle({ lineStart: 11, lineEnd: 13 })).toBe("第 11–13 行内容");
  });

  it("formats a Word section spanning multiple paragraphs", () => {
    const locator = {
      paragraphStart: 4,
      paragraphEnd: 6,
      section: "工作经历",
    };

    expect(formatEvidencePosition(locator)).toBe("第 4–6 段");
    expect(formatEvidenceTitle(locator)).toBe("工作经历");
  });
});
