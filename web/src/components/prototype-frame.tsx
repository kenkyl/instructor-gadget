// A seeded prototype (spec §4.5) is HTML/JS from the server. It runs only in a sandboxed iframe
// (CLAUDE.md): scripts allowed, but no same-origin, so it can't read cookies, storage or the app's
// DOM, or call /api as the learner. It's never injected into the page itself. It brings its own
// (light) styling, so it sits in its own inset frame.
export function PrototypeFrame({ title, html }: { title: string; html: string }) {
  return (
    <div className="bg-muted rounded-lg border p-1.5">
      <iframe
        title={title}
        sandbox="allow-scripts"
        srcDoc={html}
        className="w-full rounded-md bg-white"
        style={{ height: "46rem" }}
      />
    </div>
  );
}
