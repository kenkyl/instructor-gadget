// Mastery as a short meter in its band's colour, with the band named (colour is never the only cue).
import type { Schemas } from "@/lib/api";
import { BAND_TONE, pct } from "@/lib/labels";
import { cn } from "@/lib/utils";

const FILL = { green: "bg-green", yellow: "bg-yellow", red: "bg-red" } as Record<string, string>;
const INK = { green: "text-green-ink", yellow: "text-yellow-ink", red: "text-red-ink" } as Record<string, string>;

export function MasteryMeter({ band, mastery }: { band: Schemas["Band"]; mastery: number }) {
  const tone = BAND_TONE[band];
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="bg-muted h-1.5 w-16 overflow-hidden rounded-full"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(mastery * 100)}
        aria-label="Mastery"
      >
        <span className={cn("block h-full rounded-full", FILL[tone])} style={{ width: pct(mastery) }} />
      </span>
      <span className={cn("font-medium capitalize", INK[tone])}>{band}</span>
      <span className="num text-foreground">{pct(mastery)}</span>
    </span>
  );
}
