import { Page } from "@/components/app-shell";

import { HealthStatus } from "../health-status";

export default function StatusPage() {
  return (
    <Page className="space-y-6 [&>*]:max-w-xl">
      <header className="space-y-2">
        <h1>Stack status</h1>
        <p className="text-muted-foreground">Browser → Next.js → FastAPI → Postgres and Redis</p>
      </header>
      <HealthStatus />
    </Page>
  );
}
