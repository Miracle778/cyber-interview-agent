export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface RequestOptions {
  method?: string;
  body?: BodyInit;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

function ensureSameOriginApiPath(path: string): void {
  const locationOrigin = globalThis.location?.origin;
  const baseOrigin =
    locationOrigin && locationOrigin !== "null"
      ? locationOrigin
      : "http://localhost";
  let resolved: URL;
  try {
    resolved = new URL(path, baseOrigin);
  } catch {
    throw new ApiError("invalid_api_path", "请求地址不合法");
  }
  if (
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.includes("\\") ||
    resolved.origin !== baseOrigin ||
    !resolved.pathname.startsWith("/api/")
  ) {
    throw new ApiError("invalid_api_path", "请求地址必须是当前应用的 API 路径");
  }
}

async function readErrorBody(response: Response): Promise<{ code?: string; message?: string }> {
  try {
    const body = (await response.json()) as unknown;
    if (body && typeof body === "object" && ("code" in body || "message" in body)) {
      const record = body as { code?: string; message?: string };
      return { code: record.code, message: record.message };
    }
  } catch {
    /* non-JSON error body */
  }
  return {};
}

/**
 * Generic API request helper. Serializes errors to ApiError(code, message) and
 * treats 204 No Content as an empty (void) result without parsing a body.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  ensureSameOriginApiPath(path);
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.body,
    signal: options.signal,
  });
  if (!response.ok) {
    const errorBody = await readErrorBody(response);
    throw new ApiError(errorBody.code ?? "api_error", errorBody.message ?? "请求失败");
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function apiGet<T>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}): Promise<T> {
  return apiRequest<T>(path, { ...options, method: "GET" });
}

export async function apiPost<TRequest, TResponse>(path: string, payload: TRequest, options: Omit<RequestOptions, "method" | "body"> = {}): Promise<TResponse> {
  return apiRequest<TResponse>(path, { ...options, method: "POST", body: JSON.stringify(payload) });
}

export function apiUpload<T>(path: string, formData: FormData, options: Omit<RequestOptions, "method" | "body"> = {}): Promise<T> {
  return apiRequest<T>(path, { ...options, method: "POST", body: formData });
}

export const apiPatch = <TRequest, TResponse>(path: string, payload: TRequest): Promise<TResponse> =>
  apiRequest<TResponse>(path, { method: "PATCH", body: JSON.stringify(payload) });

export const apiPut = <TRequest, TResponse>(path: string, payload: TRequest): Promise<TResponse> =>
  apiRequest<TResponse>(path, { method: "PUT", body: JSON.stringify(payload) });

export const apiDelete = (path: string): Promise<void> => apiRequest<void>(path, { method: "DELETE" });
