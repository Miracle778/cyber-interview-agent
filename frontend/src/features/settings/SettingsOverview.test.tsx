import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsOverview, type SettingsStatusItem } from "./SettingsOverview";

const items: SettingsStatusItem[] = [
  {
    id: "workspace",
    title: "工作区",
    status: "已就绪",
    description: "/tmp/cyber-demo",
    tone: "success",
    section: "workspace",
  },
  {
    id: "providers",
    title: "Provider",
    status: "待配置",
    description: "尚未添加 Provider",
    tone: "warning",
    section: "models",
  },
];

describe("SettingsOverview", () => {
  it("renders status items and one recommended next action", () => {
    const onSelect = vi.fn();

    render(
      <SettingsOverview
        items={items}
        recommendedSection="models"
        onSelect={onSelect}
      />,
    );

    expect(screen.getByRole("heading", { name: "配置概览" })).toBeInTheDocument();
    expect(screen.getByText("尚未添加 Provider")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一步：配置模型服务" }));
    expect(onSelect).toHaveBeenCalledWith("models");
  });
});
