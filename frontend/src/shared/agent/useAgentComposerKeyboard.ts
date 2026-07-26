import {
  type CompositionEventHandler,
  type KeyboardEventHandler,
  useEffect,
  useRef,
} from "react";

interface AgentComposerKeyboardHandlers {
  onCompositionStart: CompositionEventHandler<HTMLTextAreaElement>;
  onCompositionEnd: CompositionEventHandler<HTMLTextAreaElement>;
  onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>;
}

export function useAgentComposerKeyboard(onSend: () => void): AgentComposerKeyboardHandlers {
  const onSendRef = useRef(onSend);
  const composing = useRef(false);
  const compositionJustEnded = useRef(false);
  const compositionResetTimer = useRef<number | null>(null);
  onSendRef.current = onSend;

  useEffect(() => () => {
    if (compositionResetTimer.current !== null) {
      window.clearTimeout(compositionResetTimer.current);
    }
  }, []);

  return {
    onCompositionStart: () => {
      composing.current = true;
      compositionJustEnded.current = false;
      if (compositionResetTimer.current !== null) {
        window.clearTimeout(compositionResetTimer.current);
        compositionResetTimer.current = null;
      }
    },
    onCompositionEnd: () => {
      composing.current = false;
      compositionJustEnded.current = true;
      compositionResetTimer.current = window.setTimeout(() => {
        compositionJustEnded.current = false;
        compositionResetTimer.current = null;
      }, 0);
    },
    onKeyDown: (event) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      if (
        composing.current
        || compositionJustEnded.current
        || event.nativeEvent.isComposing
        || event.nativeEvent.keyCode === 229
      ) return;
      event.preventDefault();
      onSendRef.current();
    },
  };
}
