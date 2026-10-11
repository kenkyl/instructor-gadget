"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { apiGet, apiPost, type Schemas } from "@/lib/api";

type SeededUser = Schemas["SeededUser"];

export default function LoginPage() {
  const router = useRouter();
  const [users, setUsers] = useState<SeededUser[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<SeededUser[]>("/users/seeded").then(setUsers, (e: Error) => setError(e.message));
  }, []);

  async function login(username: string) {
    setBusy(username);
    try {
      await apiPost("/auth/login", { username });
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-md p-10 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Instructor</h1>
        <p className="text-muted-foreground">Choose a user to continue.</p>
      </div>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <div className="space-y-3">
        {users.map((u) => (
          <Card key={u.username} size="sm">
            <CardHeader className="grid-cols-[1fr_auto] items-center">
              <div>
                <CardTitle>{u.username}</CardTitle>
                <CardDescription>{u.display_name}</CardDescription>
              </div>
              <Button onClick={() => login(u.username)} disabled={busy !== null}>
                {busy === u.username ? "Signing in…" : "Continue"}
              </Button>
            </CardHeader>
          </Card>
        ))}
      </div>
    </main>
  );
}
