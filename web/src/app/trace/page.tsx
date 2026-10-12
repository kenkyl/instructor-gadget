import { Suspense } from "react";

import TracePage from "./trace-client";

// The client component reads the course filter from the URL (useSearchParams). With
// cacheComponents on, Next 16 needs URL data behind a Suspense boundary.
export default function Page() {
  return (
    <Suspense fallback={<p className="p-10 text-muted-foreground">Loading…</p>}>
      <TracePage />
    </Suspense>
  );
}
