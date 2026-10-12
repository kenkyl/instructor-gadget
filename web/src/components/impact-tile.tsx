import type { ReactNode } from "react";

import type { Schemas } from "@/lib/api";
import { pct } from "@/lib/labels";

// The cache's measured effect: hits cost nothing and log the original generation's cost and time,
// so these numbers are read from the log, not estimated (ADR-0027). Cyan is the system-telemetry
// tone (ADR-0025). Used by the learner's trace and the org admin's impact view.
type Impact = Schemas["CacheImpact"];

export const usd = (x: number) => `$${x.toFixed(x >= 1 ? 2 : 3)}`;
export const dur = (ms: number) =>
  ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;

export function ImpactTile({ impact: i, scope }: { impact: Impact; scope: string }) {
  const hits = i.exact_hits + i.semantic_hits;
  const without = i.spent_usd + i.saved_usd;
  return (
    <section
      aria-labelledby="impact-heading"
      className="border-cyan/40 space-y-5 rounded-lg border p-5 sm:p-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="impact-heading" className="flex items-center gap-2">
          <span className="bg-cyan size-2 rounded-full" aria-hidden="true" />
          Cache impact
        </h2>
        <span className="text-muted-foreground text-sm">{scope}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
        <Metric
          label="Hit rate"
          value={i.hit_rate === null ? "–" : pct(i.hit_rate)}
        >
          {hits} of {i.lookups} lookups
        </Metric>
        <Metric label="Calls avoided" value={String(hits)}>
          {i.exact_hits} exact · {i.semantic_hits} semantic
        </Metric>
        <Metric label="Saved" value={usd(i.saved_usd)}>
          spent {usd(i.spent_usd)}
        </Metric>
        <Metric
          label="Time saved"
          value={dur(Math.round(i.saved_seconds * 1000))}
        >
          of model generation
        </Metric>
      </dl>
      {without > 0 && (
        <div className="space-y-1.5">
          <div
            className="bg-muted flex h-2 overflow-hidden rounded-full"
            aria-hidden="true"
          >
            <span
              className="bg-foreground/35"
              style={{ width: `${(i.spent_usd / without) * 100}%` }}
            />
            <span
              className="bg-cyan"
              style={{ width: `${(i.saved_usd / without) * 100}%` }}
            />
          </div>
          <p className="text-muted-foreground text-sm">
            Without the cache these calls would have cost{" "}
            <span className="num text-foreground">{usd(without)}</span>; the
            cache paid for{" "}
            <span className="num text-cyan-ink">
              {pct(i.saved_usd / without)}
            </span>{" "}
            of it.
          </p>
        </div>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-0.5">
      <dt className="text-muted-foreground text-sm">{label}</dt>
      <dd className="num text-strong text-2xl font-semibold">{value}</dd>
      <dd className="text-muted-foreground text-xs">{children}</dd>
    </div>
  );
}
