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

  if (error) return <p className="text-red-600">API unreachable: {error}</p>;
  if (!health) return <p className="text-zinc-500">Checking…</p>;

  const rows: [string, string][] = [
    ["Overall", health.status],
    ["Postgres", health.postgres],
    ["Redis", `${health.redis} (v${health.redis_version ?? "?"})`],
    ["Redis Query Engine", health.query_engine],
  ];
  return (
    <ul className="space-y-1 font-mono text-sm">
      {rows.map(([name, value]) => (
        <li key={name}>
          <span className={value.startsWith("ok") ? "text-green-600" : "text-red-600"}>●</span>{" "}
          {name}: {value}
        </li>
      ))}
    </ul>
  );
}
