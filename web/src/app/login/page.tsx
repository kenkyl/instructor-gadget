"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Page } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
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
      // Reset before navigating: Next 16 keeps this page alive (hidden) after replace, so after
      // a logout it comes back exactly as left, still "Signing in…" for the last user.
      setBusy(null);
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <Page className="space-y-10 sm:py-20 [&>*]:max-w-xl">
      <div className="space-y-3">
        <h1>An instructor that checks what you actually know</h1>
        <p className="text-muted-foreground max-w-[56ch] text-lg">
          It tests where you really are, teaches one concept at a time, and re-plans from how you do
          on each quiz.
        </p>
      </div>
      <section className="space-y-3" aria-labelledby="who">
        <h2 id="who" className="text-base">
          Continue as
        </h2>
        {error && <p className="text-destructive text-sm">{error}</p>}
        <ul className="divide-y rounded-lg border">
          {users.map((u) => (
            <li key={u.username} className="flex items-center justify-between gap-4 px-4 py-3">
              <div>
                <p className="text-strong font-semibold">{u.display_name}</p>
                <p className="text-muted-foreground text-sm">{u.username}</p>
              </div>
              <Button
                variant={busy === u.username ? "default" : "outline"}
                onClick={() => login(u.username)}
                disabled={busy !== null}
              >
                {busy === u.username ? "Signing in…" : "Continue"}
              </Button>
            </li>
          ))}
        </ul>
      </section>
    </Page>
  );
}
