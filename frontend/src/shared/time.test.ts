import { describe, expect, it } from "vitest";
import {
  elapsedSeconds,
  formatBeijingDate,
  formatBeijingDateTime,
  formatBeijingTime,
  formatBeijingTimestamp,
  formatElapsedSeconds,
} from "./time";

describe("API timestamps", () => {
  it("treats SQLite timestamps as UTC and renders Beijing time", () => {
    expect(formatBeijingTime("2026-07-15 14:39:06")).toBe("22:39:06");
    expect(formatBeijingDateTime("2026-07-27 10:13:00")).toBe("2026/07/27 18:13");
    expect(formatBeijingDate("2026-07-27 18:30:00")).toBe("2026/07/28");
    expect(formatBeijingTimestamp("2026-07-27 10:13:00", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })).toBe("7/27 18:13");
  });

  it("calculates elapsed time across mixed UTC timestamp formats", () => {
    expect(elapsedSeconds("2026-07-15T14:39:00+00:00", "2026-07-15 14:39:06")).toBe(6);
    expect(formatElapsedSeconds(6)).toBe("6 秒");
    expect(formatElapsedSeconds(65)).toBe("1 分 5 秒");
  });
});
