"use client";

// The lesson diagram is LLM-written Mermaid. Two layers (CLAUDE.md: LLM output renders only in
// a sandboxed iframe): mermaid's "strict" security level sanitizes the SVG it produces, and the
// SVG is shown in a srcdoc iframe with an empty sandbox (no scripts, no same-origin), so even a
// sanitizer bug can't reach the page. Mermaid is large, so it loads only when a diagram shows.
import { useEffect, useId, useState } from "react";

type Rendered = { svg: string; ratio: string } | { error: string };

export function MermaidDiagram({ source }: { source: string }) {
  const id = `mmd-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [out, setOut] = useState<Rendered | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
        const { svg } = await mermaid.render(id, source);
        const box = /viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"/.exec(svg);
        if (!cancelled) setOut({ svg, ratio: box ? `${box[1]} / ${box[2]}` : "16 / 9" });
      } catch (e) {
        if (!cancelled) setOut({ error: (e as Error).message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (out === null) return <p className="text-muted-foreground text-sm">Drawing the diagram…</p>;
  if ("error" in out) {
    return (
      <div className="space-y-1">
        <p className="text-muted-foreground text-sm">The diagram couldn’t be drawn; its source:</p>
        <pre className="bg-muted overflow-x-auto rounded p-3 text-xs">{source}</pre>
      </div>
    );
  }
  return (
    <iframe
      title="Lesson diagram"
      sandbox=""
      srcDoc={`<!doctype html><style>html,body{margin:0;background:#fff}svg{display:block;width:100%;height:auto;max-width:100%!important}</style>${out.svg}`}
      className="w-full rounded border bg-white"
      style={{ aspectRatio: out.ratio, maxHeight: "32rem" }}
    />
  );
}
