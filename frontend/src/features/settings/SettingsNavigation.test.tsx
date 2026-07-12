import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsNavigation, type SettingsSection } from "./SettingsNavigation";

describe("SettingsNavigation", () => {
  afterEach(cleanup);

  it("marks the current section and routes to another section", () => {
    const onSelect = vi.fn<(section: SettingsSection) => void>();

    render(<SettingsNavigation current="overview" onSelect={onSelect} />);

    expect(screen.getByRole("navigation", { name: "设置分组" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "配置概览" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(screen.getByRole("button", { name: "模型服务" }));
    expect(onSelect).toHaveBeenCalledWith("models");
  });

  it("disables sections that cannot run before workspace restoration", () => {
    render(
      <SettingsNavigation
        current="overview"
        onSelect={vi.fn()}
        disabledSections={["models", "diagnostics"]}
      />,
    );

    expect(screen.getByRole("button", { name: "模型服务" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "运行诊断" })).toBeDisabled();
  });
});
