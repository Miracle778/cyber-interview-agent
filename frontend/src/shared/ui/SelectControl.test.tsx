import { fireEvent, render, screen } from "@testing-library/react";
import { Bot } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { SelectControl } from "./SelectControl";


describe("SelectControl", () => {
  it("keeps native select semantics while applying the shared visual shell", () => {
    const onChange = vi.fn();
    const { container } = render(
      <SelectControl
        aria-label="Agent"
        label="Agent 类型"
        icon={<Bot />}
        value="all"
        onChange={onChange}
      >
        <option value="all">全部 Agent</option>
        <option value="review">复习助手</option>
      </SelectControl>,
    );

    const select = screen.getByRole("combobox", { name: "Agent" });
    expect(select).toHaveValue("all");
    expect(container.querySelector(".select-control")).toHaveAttribute(
      "data-layout",
      "stacked",
    );
    expect(screen.getByText("Agent 类型")).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "review" } });
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("supports compact and disabled controls", () => {
    render(
      <SelectControl aria-label="思考强度" controlSize="sm" disabled defaultValue="low">
        <option value="low">低</option>
      </SelectControl>,
    );

    const select = screen.getByRole("combobox", { name: "思考强度" });
    expect(select).toBeDisabled();
    expect(select.closest(".select-control")).toHaveAttribute("data-size", "sm");
    expect(select.closest(".select-control")).toHaveAttribute("data-disabled", "true");
  });
});
