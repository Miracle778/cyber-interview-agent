import { afterEach, describe, expect, it, vi } from "vitest";
import { createOperationId } from "./operationId";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("createOperationId", () => {
  it("uses a browser UUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "uuid-1" });

    expect(createOperationId("profile")).toBe("profile-uuid-1");
  });

  it("keeps fallback identifiers unique within the page session", () => {
    vi.stubGlobal("crypto", {});
    vi.spyOn(Date, "now").mockReturnValue(1000);

    const first = createOperationId("review");
    const second = createOperationId("review");

    expect(first).not.toBe(second);
    expect(first).toMatch(/^review-1000-\d+$/);
  });
});
