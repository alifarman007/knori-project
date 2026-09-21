/**
 * The one place the browser talks to `/api/v1`.
 *
 * Three things every call needs and none should have to remember:
 *   - `credentials: "include"`, because the session is an httpOnly cookie;
 *   - `X-Requested-With: knori` on non-GET, which is half of the CSRF defence
 *     (the API checks Origin for the other half);
 *   - problem+json parsing, so a failure arrives as a typed `ApiError` with a
 *     request id the person can quote in a bug report.
 */

import type { ProblemDetail } from "@/lib/types";

/**
 * Where the browser sends `/api/v1` calls.
 *
 * The default is same-origin, because `next.config.ts` rewrites `/api/*` to the
 * FastAPI origin and a first-party path keeps the httpOnly session cookie
 * working without SameSite=None. `NEXT_PUBLIC_API_URL` points straight at the
 * API instead, for a deployment where the two are not behind one host.
 */
function resolveBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE;
  if (base) return base.replace(/\/$/, "");
  const origin = process.env.NEXT_PUBLIC_API_URL;
  if (origin) return `${origin.replace(/\/$/, "")}/api/v1`;
  return "/api/v1";
}

export const API_BASE = resolveBase();

/** Absolute URL for the few callers that cannot use `fetch`, e.g. EventSource. */
export function apiUrl(path: string): string {
  if (path.startsWith("http")) return path;
  const url = `${API_BASE}${path}`;
  if (url.startsWith("http") || typeof window === "undefined") return url;
  return new URL(url, window.location.origin).toString();
}

/** Both problem+json error shapes collapse to one map the forms can read. */
function normaliseFieldErrors(errors: ProblemDetail["errors"]): Record<string, string[]> {
  if (!errors) return {};
  if (!Array.isArray(errors)) return errors;
  const map: Record<string, string[]> = {};
  for (const item of errors) {
    if (!item?.field) continue;
    (map[item.field] ??= []).push(item.message);
  }
  return map;
}

export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string | undefined;
  readonly code: string | undefined;
  readonly requestId: string | undefined;
  /** Seconds to wait, on a 429. */
  readonly retryAfter: number | undefined;
  /** Field name -> messages. Empty object when the failure was not a form. */
  readonly fieldErrors: Record<string, string[]>;

  constructor(status: number, problem: Partial<ProblemDetail>, requestId?: string) {
    const title = problem.title ?? defaultTitle(status);
    super(problem.detail ?? title);
    this.name = "ApiError";
    this.status = status;
    this.title = title;
    this.detail = problem.detail;
    this.code = problem.code;
    this.requestId = problem.request_id ?? requestId;
    this.retryAfter = problem.retry_after;
    this.fieldErrors = normaliseFieldErrors(problem.errors);
  }

  /** True when retrying the identical request could plausibly work. */
  get isTransient(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** First message for a field, for inline form errors. */
  fieldError(field: string): string | undefined {
    return this.fieldErrors[field]?.[0];
  }
}

function defaultTitle(status: number): string {
  if (status === 0) return "KnoRI could not be reached";
  if (status === 401) return "Please sign in again";
  if (status === 403) return "Not allowed";
  if (status === 404) return "Not found";
  if (status === 409) return "That conflicts with something else";
  if (status === 429) return "Too many requests";
  if (status >= 500) return "Something went wrong on our side";
  return "That request did not work";
}

export interface RequestOptions {
  signal?: AbortSignal;
  /** Extra headers. Content-Type is set for you when a body is present. */
  headers?: Record<string, string>;
  /** Query string parameters; null and undefined are dropped. */
  query?: Record<string, string | number | boolean | null | undefined>;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined) continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("x-request-id") ?? undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("json")) {
    try {
      const body = (await response.json()) as Partial<ProblemDetail>;
      return new ApiError(response.status, body, requestId);
    } catch {
      // Fall through to the plain-status error below.
    }
  }
  return new ApiError(response.status, {}, requestId);
}

/** Low-level request. Prefer the `api` helpers below. */
export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (method !== "GET" && method !== "HEAD") {
    headers["X-Requested-With"] = "knori";
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      credentials: "include",
      cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, { detail: "Check your connection and try again." });
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, body, options),
  delete: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("DELETE", path, body, options),
};

/**
 * POST that returns `text/event-stream`.
 *
 * EventSource cannot POST, so the chat composer reads the body itself. Frames
 * arrive as `event: <name>\ndata: <json>\n\n`; partial frames are held back
 * until the blank line that ends them.
 */
export async function postStream(
  path: string,
  body: unknown,
  onFrame: (event: string, data: unknown) => void,
  options: RequestOptions = {},
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        "X-Requested-With": "knori",
        ...options.headers,
      },
      credentials: "include",
      cache: "no-store",
      body: JSON.stringify(body),
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, { detail: "Check your connection and try again." });
  }

  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new ApiError(0, { detail: "The reply stream was empty." });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split = buffer.indexOf("\n\n");
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const parsed = parseFrame(frame);
      if (parsed) onFrame(parsed.event, parsed.data);
      split = buffer.indexOf("\n\n");
    }
  }
}

function parseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) as unknown };
  } catch {
    return { event, data: raw };
  }
}

/** Turn any thrown value into something safe to put on screen. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail ?? error.title;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

/**
 * Accept both list shapes.
 *
 * Paginated endpoints send `{items, next_cursor}`; the small nested ones
 * (`/memory/items/{id}/sources`, `/recognitions/{id}/history`) may send a bare
 * array. Reading either here means one endpoint changing its mind cannot blank
 * a screen.
 */
export function unwrapList<T>(raw: unknown): T[] {
  if (Array.isArray(raw)) return raw as T[];
  if (raw && typeof raw === "object") {
    const items = (raw as { items?: unknown }).items;
    if (Array.isArray(items)) return items as T[];
  }
  return [];
}

/** Trigger a browser download of an authenticated endpoint (the data export). */
export async function download(path: string, filename: string): Promise<void> {
  const response = await fetch(buildUrl(path), {
    credentials: "include",
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw await toApiError(response);

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
