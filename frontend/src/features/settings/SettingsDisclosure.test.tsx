import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsDisclosure } from "./SettingsDisclosure";

describe("SettingsDisclosure", () => {
  it("keeps diagnostic content collapsed until requested", () => {
    render(<SettingsDisclosure id="runtime" title="Runtime" description="运行自检"><button>运行自检</button></SettingsDisclosure>);
    const trigger = screen.getByRole("button", { name: /Runtime/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "运行自检" })).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "运行自检" })).toBeInTheDocument();
  });
});
