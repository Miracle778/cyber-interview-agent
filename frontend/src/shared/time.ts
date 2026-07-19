const SQLITE_UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/;

export function parseApiTimestamp(value: string): Date {
  const normalized = SQLITE_UTC_TIMESTAMP.test(value)
    ? `${value.replace(" ", "T")}Z`
    : value;
  return new Date(normalized);
}

export function formatBeijingTime(value: string, includeSeconds = true): string | null {
  const date = parseApiTimestamp(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

export function elapsedSeconds(startedAt: string, finishedAt: string): number | null {
  const start = parseApiTimestamp(startedAt).getTime();
  const finish = parseApiTimestamp(finishedAt).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(finish) || finish < start) return null;
  return Math.round((finish - start) / 1000);
}

export function formatElapsedSeconds(seconds: number): string {
  const safe = Math.max(0, Math.round(seconds));
  return safe < 60 ? `${safe} 秒` : `${Math.floor(safe / 60)} 分 ${safe % 60} 秒`;
}
