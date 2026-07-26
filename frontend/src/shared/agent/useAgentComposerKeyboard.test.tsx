import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAgentComposerKeyboard } from "./useAgentComposerKeyboard";

function KeyboardProbe({ onSend }: { onSend: () => void }) {
  const keyboard = useAgentComposerKeyboard(onSend);
  return <textarea aria-label="消息" {...keyboard} />;
}

describe("useAgentComposerKeyboard", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("sends on ordinary Enter and keeps Shift+Enter for a newline", () => {
    const onSend = vi.fn();
    render(<KeyboardProbe onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: "消息" });

    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("does not send while the IME is composing or reports keyCode 229", () => {
    const onSend = vi.fn();
    render(<KeyboardProbe onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: "消息" });

    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, {
      key: "Enter",
      isComposing: true,
      keyCode: 229,
    });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not send on the Enter event that ends IME composition", () => {
    vi.useFakeTimers();
    const onSend = vi.fn();
    render(<KeyboardProbe onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: "消息" });

    fireEvent.compositionStart(input);
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();

    vi.runAllTimers();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});
