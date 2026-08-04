let fallbackSequence = 0;

/**
 * Creates a unique client operation identifier, not an authentication secret.
 * Modern browsers use a UUID; the fallback remains unique within one page
 * session without claiming to provide cryptographic randomness.
 */
export function createOperationId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `${prefix}-${uuid}`;
  fallbackSequence += 1;
  return `${prefix}-${Date.now()}-${fallbackSequence}`;
}
