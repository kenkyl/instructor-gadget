import { Suspense } from "react";

import QuizPage from "./quiz-client";

// URL data (useParams/useSearchParams) sits behind a Suspense boundary (Next 16 cacheComponents).
export default function Page() {
  return (
    <Suspense fallback={<p className="p-10 text-muted-foreground">Loading…</p>}>
      <QuizPage />
    </Suspense>
  );
}
