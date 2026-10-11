"use client";

// The prerequisite gate (spec §4.8): a locked concept can be opened anyway, after a specific
// warning about what will break. The override is logged and becomes a new plan version.
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
    <div className="space-y-3 rounded border p-4">
      <p className="font-medium">This concept is locked until its prerequisites are solid.</p>
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
          <p className="text-sm">
            Not yet solid: {warning.unmet_prereqs.map((u) => u.title).join(", ") || "—"}
          </p>
          <p className="rounded bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
            {warning.warning}
          </p>
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
