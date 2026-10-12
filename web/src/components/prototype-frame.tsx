// A seeded prototype (spec §4.5) is HTML/JS from the server. It runs only in a sandboxed iframe
// (CLAUDE.md): scripts allowed, but no same-origin, so it can't read cookies, storage or the app's
// DOM, or call /api as the learner. It's never injected into the page itself.
export function PrototypeFrame({ title, html }: { title: string; html: string }) {
  return (
    <iframe
      title={title}
      sandbox="allow-scripts"
      srcDoc={html}
      className="w-full rounded border bg-white"
      style={{ height: "46rem" }}
    />
  );
}
