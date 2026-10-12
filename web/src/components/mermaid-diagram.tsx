"use client";

// The lesson diagram is LLM-written Mermaid. Two layers (CLAUDE.md: LLM output renders only in
// a sandboxed iframe): mermaid's "strict" security level sanitizes the SVG it produces, and the
// SVG is shown in a srcdoc iframe with an empty sandbox (no scripts, no same-origin), so even a
// sanitizer bug can't reach the page. Mermaid is large, so it loads only when a diagram shows.
// The iframe can't read the page's CSS variables, so the Solarized colours are passed in as hex
// and the diagram re-renders when the theme changes.
import { useEffect, useId, useState } from "react";

import { SOLARIZED as S, type Theme } from "@/lib/theme";
import { useTheme } from "@/lib/use-theme";

type Rendered = { svg: string; ratio: string; bg: string } | { error: string };

function themeVariables(theme: Theme) {
  const dark = theme === "dark";
  return {
    darkMode: dark,
    background: dark ? S.base03 : S.base3,
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
    fontSize: "15px",
    primaryColor: dark ? S.base02 : S.base2,
    primaryTextColor: dark ? S.base2 : S.base02,
    primaryBorderColor: S.blue,
    secondaryColor: dark ? S.base02 : S.base2,
    secondaryTextColor: dark ? S.base2 : S.base02,
    secondaryBorderColor: S.cyan,
    tertiaryColor: dark ? S.base03 : S.base3,
    tertiaryTextColor: dark ? S.base1 : S.base01,
    tertiaryBorderColor: dark ? S.base01 : S.base1,
    lineColor: dark ? S.base0 : S.base00,
    textColor: dark ? S.base1 : S.base01,
    mainBkg: dark ? S.base02 : S.base2,
    nodeBorder: S.blue,
    clusterBkg: dark ? S.base03 : S.base3,
    clusterBorder: dark ? S.base01 : S.base1,
    edgeLabelBackground: dark ? S.base03 : S.base3,
    actorBkg: dark ? S.base02 : S.base2,
    actorBorder: S.blue,
    actorTextColor: dark ? S.base2 : S.base02,
    signalColor: dark ? S.base1 : S.base01,
    signalTextColor: dark ? S.base1 : S.base01,
    noteBkgColor: dark ? S.base02 : S.base2,
    noteBorderColor: S.yellow,
    noteTextColor: dark ? S.base1 : S.base01,
  };
}

export function MermaidDiagram({ source }: { source: string }) {
  const id = `mmd-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const theme = useTheme();
  const [out, setOut] = useState<Rendered | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        const themeVars = themeVariables(theme);
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: themeVars });
        const { svg } = await mermaid.render(id, source);
        const box = /viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"/.exec(svg);
        if (!cancelled) setOut({ svg, ratio: box ? `${box[1]} / ${box[2]}` : "16 / 9", bg: themeVars.background });
      } catch (e) {
        if (!cancelled) setOut({ error: (e as Error).message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, source, theme]);

  if (out === null) return <p className="text-muted-foreground text-sm">Drawing the diagram…</p>;
  if ("error" in out) {
    return (
      <div className="space-y-1">
        <p className="text-muted-foreground text-sm">The diagram couldn’t be drawn; its source:</p>
        <pre className="bg-muted num overflow-x-auto rounded-md p-3 text-xs">{source}</pre>
      </div>
    );
  }
  return (
    <iframe
      title="Lesson diagram"
      sandbox=""
      srcDoc={`<!doctype html><style>html,body{margin:0;background:${out.bg}}svg{display:block;width:100%;height:auto;max-width:100%!important}</style>${out.svg}`}
      className="w-full rounded-lg border p-2"
      style={{ aspectRatio: out.ratio, maxHeight: "32rem", background: out.bg }}
    />
  );
}
