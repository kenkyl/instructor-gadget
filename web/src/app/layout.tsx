import type { Metadata } from "next";
import { Atkinson_Hyperlegible_Mono, Atkinson_Hyperlegible_Next } from "next/font/google";

import { THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

// Atkinson Hyperlegible (Braille Institute) is designed so similar letterforms can't be confused;
// the mono cut is used only for values that are data.
const atkinson = Atkinson_Hyperlegible_Next({
  variable: "--font-atkinson",
  subsets: ["latin"],
  adjustFontFallback: false, // next/font has no metrics for Atkinson; skip the size-adjusted fallback
});

const atkinsonMono = Atkinson_Hyperlegible_Mono({
  variable: "--font-atkinson-mono",
  subsets: ["latin"],
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "Instructor",
  description: "An AI instructor that checks what you actually know.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme is set by THEME_SCRIPT before paint, so React must accept the DOM's value.
    <html
      lang="en"
      className={`${atkinson.variable} ${atkinsonMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
