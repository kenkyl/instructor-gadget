// Thin typed wrapper over fetch. Types come from FastAPI's OpenAPI schema (`make types`),
// so the backend's Pydantic models are the single source of truth for the contract.
// All calls go to same-origin /api/*, which Next proxies to FastAPI; the session cookie
// (HttpOnly) rides along automatically.
import type { components } from "@/lib/api-types";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res, `${method} /api${path}`));
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

// FastAPI errors carry {"detail": "..."}; show that when it's a plain message.
async function errorMessage(res: Response, what: string): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // not JSON
  }
  return `${what} failed: ${res.status}`;
}

export const apiGet = <T>(path: string) => request<T>("GET", path);
export const apiPost = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
export const apiDelete = <T>(path: string) => request<T>("DELETE", path);
