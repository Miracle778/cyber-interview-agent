import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { PrimaryNavigation } from "./PrimaryNavigation";


afterEach(cleanup);

describe("PrimaryNavigation", () => {
  it("shows the live Agent count and opens the running filter", () => {
    render(
      <MemoryRouter>
        <PrimaryNavigation activeAgentCount={3} />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", {
      name: "Agent 运行中心，3 个正在运行",
    });
    expect(link).toHaveAttribute("href", "/agents?status=running");
    expect(screen.getByText("3")).toBeVisible();
  });

  it("does not show a distracting zero badge", () => {
    render(
      <MemoryRouter>
        <PrimaryNavigation activeAgentCount={0} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Agent 运行中心" })).toHaveAttribute(
      "href",
      "/agents",
    );
  });
});
