"use client";

import { useEffect, useState } from "react";

import { apiGet, type Schemas } from "@/lib/api";

type Health = Schemas["HealthResponse"];

// Fetched from the browser on purpose: this proves the /api rewrite (browser → Next → FastAPI).
export function HealthStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Health>("/health").then(setHealth, (e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="text-destructive">API unreachable: {error}</p>;
  if (!health) return <p className="text-muted-foreground">Checking…</p>;

  const rows: [string, string][] = [
    ["Overall", health.status],
    ["Postgres", `${health.postgres} (v${health.postgres_version ?? "?"})`],
    ["Redis", `${health.redis} (v${health.redis_version ?? "?"})`],
    ["Redis Query Engine", health.query_engine],
  ];
  return (
    <ul className="divide-y rounded-lg border">
      {rows.map(([name, value]) => {
        const ok = value.startsWith("ok");
        return (
          <li key={name} className="flex items-center gap-3 px-4 py-3">
            <span className={ok ? "bg-green size-2 rounded-full" : "bg-red size-2 rounded-full"} />
            <span className="text-strong font-semibold">{name}</span>
            <span className={`num ml-auto text-sm ${ok ? "text-green-ink" : "text-red-ink"}`}>{value}</span>
          </li>
        );
      })}
    </ul>
  );
}
