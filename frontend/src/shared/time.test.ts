import { describe, expect, it } from "vitest";
import { elapsedSeconds, formatBeijingTime } from "./time";

describe("API timestamps", () => {
  it("treats SQLite timestamps as UTC and renders Beijing time", () => {
    expect(formatBeijingTime("2026-07-15 14:39:06")).toBe("22:39:06");
  });

  it("calculates elapsed time across mixed UTC timestamp formats", () => {
    expect(elapsedSeconds("2026-07-15T14:39:00+00:00", "2026-07-15 14:39:06")).toBe(6);
  });
});
