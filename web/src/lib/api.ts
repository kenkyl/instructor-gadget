// Thin typed wrapper over fetch. Types come from FastAPI's OpenAPI schema (`make types`),
// so the backend's Pydantic models are the single source of truth for the contract.
import type { components } from "@/lib/api-types";

export type Schemas = components["schemas"];

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api${path} failed: ${res.status}`);
  return (await res.json()) as T;
}
