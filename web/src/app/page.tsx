import { HealthStatus } from "./health-status";

export default function Home() {
  return (
    <main className="mx-auto max-w-xl p-10 space-y-4">
      <h1 className="text-2xl font-semibold">Instructor</h1>
      <p className="text-zinc-600">Stack status (browser → Next.js → FastAPI → Postgres / Redis)</p>
      <HealthStatus />
    </main>
  );
}
