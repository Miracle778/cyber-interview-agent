import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  it("renders provider and workspace fields", () => {
    render(<SettingsPage />);
    expect(screen.getByLabelText("Provider 名称")).toBeInTheDocument();
    expect(screen.getByLabelText("Base URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Workspace Path")).toBeInTheDocument();
  });
});
