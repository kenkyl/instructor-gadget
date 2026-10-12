"use client";

// The prerequisite gate (spec §4.8): a locked concept can be opened anyway, after a specific
// warning about what will break. The override is logged and becomes a new plan version.
import { Lock } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiGet, apiPost, type Schemas } from "@/lib/api";

type OverrideWarning = Schemas["OverrideWarning"];

export function OverrideGate({
  enrollmentId,
  conceptId,
  onOpened,
}: {
  enrollmentId: string;
  conceptId: string;
  onOpened: () => void;
}) {
  const base = `/enrollments/${enrollmentId}/concepts/${conceptId}/override`;
  const [warning, setWarning] = useState<OverrideWarning | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 rounded-lg border p-5">
      <div className="flex items-start gap-3">
        <Lock className="text-muted-foreground mt-0.5 size-5 shrink-0" />
        <div className="space-y-1">
          <p className="text-strong font-semibold">This concept is locked</p>
          <p className="text-muted-foreground">It opens once the concepts it builds on are solid.</p>
        </div>
      </div>
      {!warning ? (
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => run(async () => setWarning(await apiGet<OverrideWarning>(base)))}
        >
          {busy ? "Checking what you'd miss…" : "Open it anyway…"}
        </Button>
      ) : (
        <>
          {warning.unmet_prereqs.length > 0 && (
            <div className="space-y-1">
              <p className="text-sm font-semibold">Not yet solid</p>
              <ul className="list-disc pl-5 text-sm">
                {warning.unmet_prereqs.map((u) => (
                  <li key={u.concept_id}>{u.title}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="border-yellow bg-yellow/10 rounded-r-md border-l-2 px-4 py-3">{warning.warning}</p>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await apiPost(base, { warning: warning.warning });
                onOpened();
              })
            }
          >
            I understand, open it
          </Button>
        </>
      )}
      {error && <p className="text-destructive text-sm">{error}</p>}
    </div>
  );
}
