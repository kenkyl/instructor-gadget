"use client";

// The frame every page shares: a top bar (wordmark, page-specific controls, theme toggle) and one
// left-aligned content column.
import { ChevronLeft, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useLayoutEffect, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { applyTheme, saveTheme, storedTheme, systemTheme } from "@/lib/theme";
import { useTheme } from "@/lib/use-theme";

// The mark is the plan graph in miniature: a rail of concepts with a remediation branch.
function Mark() {
  return (
    <svg viewBox="0 0 20 24" className="h-6 w-5" aria-hidden="true">
      <path d="M6 4v16" stroke="var(--rail)" strokeWidth="2" fill="none" />
      <path d="M6 7c0 3 8 2 8 5s-8 2-8 5" stroke="var(--orange)" strokeWidth="2" fill="none" />
      <circle cx="6" cy="4" r="3" fill="var(--green)" />
      <rect x="11.5" y="9.5" width="5" height="5" transform="rotate(45 14 12)" fill="var(--orange)" />
      <circle cx="6" cy="20" r="2.75" fill="var(--background)" stroke="var(--blue)" strokeWidth="2" />
    </svg>
  );
}

export function ThemeToggle() {
  const theme = useTheme();

  useLayoutEffect(() => {
    // Re-apply after React's dev remount clears <html data-theme> (a no-op in production), and
    // follow the OS setting live until the learner picks a theme themselves.
    applyTheme(storedTheme() ?? systemTheme());
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => storedTheme() ?? applyTheme(systemTheme());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={() => saveTheme(next)}
      className="text-muted-foreground hover:text-foreground hover:bg-muted grid size-8 place-items-center rounded-md transition-colors"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

export function AppBar({ children }: { children?: ReactNode }) {
  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-3xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="text-strong flex items-center gap-2 font-semibold tracking-tight">
          <Mark />
          Instructor
        </Link>
        <div className="ml-auto flex items-center gap-2">
          {children}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

export function Page({
  bar,
  className,
  children,
}: {
  bar?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <>
      <AppBar>{bar}</AppBar>
      <main className={cn("mx-auto w-full max-w-3xl px-4 py-10 sm:px-6", className)}>{children}</main>
    </>
  );
}

export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="text-muted-foreground hover:text-foreground -ml-1 inline-flex items-center gap-0.5 text-sm transition-colors"
    >
      <ChevronLeft className="size-4" />
      {children}
    </Link>
  );
}

/** Loading and failure states for a whole page, in the page frame. */
export function PageMessage({ error, children }: { error?: string | null; children: ReactNode }) {
  return (
    <Page>
      <p className={error ? "text-destructive" : "text-muted-foreground"}>{error ?? children}</p>
    </Page>
  );
}
