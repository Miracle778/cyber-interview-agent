export function sourceIdFromReference(reference: string): string {
  const separator = reference.indexOf("#");
  return separator < 0 ? reference : reference.slice(0, separator);
}

export function referencesSource(references: string[], sourceId: string): boolean {
  return references.some((reference) => sourceIdFromReference(reference) === sourceId);
}

export function uniqueSourceCount(references: string[]): number {
  return new Set(references.map(sourceIdFromReference)).size;
}
