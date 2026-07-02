import "@testing-library/jest-dom/vitest";

type EventSourceListener = (event: MessageEvent) => void;

export class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners: Record<string, EventSourceListener> = {};
  closed = false;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, callback: EventSourceListener) {
    this.listeners[type] = callback;
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    this.listeners[type]?.(new MessageEvent(type, { data: JSON.stringify(data) }));
  }

  static reset() {
    MockEventSource.instances = [];
  }
}

Object.defineProperty(globalThis, "EventSource", {
  value: MockEventSource,
  writable: true,
});
