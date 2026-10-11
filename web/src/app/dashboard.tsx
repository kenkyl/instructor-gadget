"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";

type DashboardData = Schemas["DashboardResponse"];

export function Dashboard() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<DashboardData>("/dashboard").then(setData, (e: Error) => {
      // Cookie present but session expired or revoked: the API is the real auth check.
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [router]);

  async function logout() {
    await apiPost("/auth/logout");
    router.replace("/login");
  }

  if (error) return <p className="p-10 text-destructive">{error}</p>;
  if (!data) return <p className="p-10 text-muted-foreground">Loading…</p>;

  return (
    <main className="mx-auto max-w-3xl p-10 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Hi, {data.user.username}</h1>
          <p className="text-muted-foreground text-sm">{data.user.display_name}</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Makes the cache-aside layer visible: "cache" = Redis JSON hit, "db" = rebuilt from Postgres */}
          <Badge variant="outline" title={`generated ${data.generated_at}`}>
            served from {data.served_from}
          </Badge>
          <Button variant="outline" onClick={logout}>
            Log out
          </Button>
        </div>
      </header>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">Your courses</h2>
          <Button onClick={() => router.push("/courses/new")}>New course</Button>
        </div>
        {data.courses.length === 0 ? (
          <Card>
            <CardContent className="text-muted-foreground">No courses yet.</CardContent>
          </Card>
        ) : (
          data.courses.map((c) => (
            <Card key={c.enrollment_id}>
              <CardHeader>
                <CardTitle>
                  <Link href={`/learn/${c.enrollment_id}`} className="hover:underline">
                    {c.title}
                  </Link>
                  {c.status === "complete" && " 🎓"}
                </CardTitle>
                <CardDescription>
                  {c.scope === "org" ? `Org course · ${c.org_name}` : "Personal course"} ·{" "}
                  {c.concepts_complete}/{c.concepts_total} concepts · {c.due_count} due for review
                </CardDescription>
              </CardHeader>
            </Card>
          ))
        )}
      </section>
    </main>
  );
}
