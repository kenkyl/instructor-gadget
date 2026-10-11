import { HealthStatus } from "../health-status";

export default function StatusPage() {
  return (
    <main className="mx-auto max-w-xl p-10 space-y-4">
      <h1 className="text-2xl font-semibold">Stack status</h1>
      <p className="text-muted-foreground">browser → Next.js → FastAPI → Postgres / Redis</p>
      <HealthStatus />
    </main>
  );
}
