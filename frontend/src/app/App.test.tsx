import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the MVP shell", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Cyber Interview Agent" })).toBeInTheDocument();
    expect(screen.getByText("复习闭环 MVP")).toBeInTheDocument();
  });
});
