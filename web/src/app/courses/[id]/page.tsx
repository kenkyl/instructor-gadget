import { Suspense } from "react";

import CoursePage from "./course-client";

// The client component reads the URL (useParams). With cacheComponents on, Next 16 needs URL
// data behind a Suspense boundary so the rest of the route can prerender.
export default function Page() {
  return (
    <Suspense fallback={<p className="p-10 text-muted-foreground">Loading…</p>}>
      <CoursePage />
    </Suspense>
  );
}
