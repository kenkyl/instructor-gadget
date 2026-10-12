"use client";

// The org's internal docs: what org courses are grounded in (spec §5). Members read them; admins
// add them. Each doc's headings become the section anchors a lesson's citations point at, so the
// list shows them. Docs never change once uploaded (ADR-0028): courses are pinned to a version.
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from "react";

import { BackLink, Page, PageMessage } from "@/components/app-shell";
import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";

type OrgMembership = Schemas["OrgMembershipOut"];
type DocSummary = Schemas["OrgDocSummary"];
type DocDetail = Schemas["OrgDocDetail"];

const kb = (chars: number) => `${Math.max(1, Math.round(chars / 1000))} KB`;

export default function OrgDocsPage() {
  const router = useRouter();
  const [org, setOrg] = useState<OrgMembership | null>(null);
  const [docs, setDocs] = useState<DocSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (slug: string) => setDocs(await apiGet<DocSummary[]>(`/orgs/${slug}/docs`)),
    [],
  );

  useEffect(() => {
    // Phase 1 has one org per user; the first membership is the org.
    apiGet<OrgMembership[]>("/orgs")
      .then(async (orgs) => {
        if (orgs.length === 0) return setError("You're not in an org, so there are no org docs.");
        setOrg(orgs[0]);
        await load(orgs[0].slug);
      })
      .catch((e: Error) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setError(e.message);
      });
  }, [load, router]);

  if (!org || !docs) return <PageMessage error={error}>Loading your org’s docs…</PageMessage>;

  return (
    <Page className="space-y-8">
      <header className="space-y-3">
        <BackLink href="/">Courses</BackLink>
        <h1>{org.name} docs</h1>
        <p className="text-muted-foreground max-w-[64ch]">
          Org courses are grounded in these docs: lessons cite the section they draw from, and say
          so when something isn&apos;t covered here.
        </p>
      </header>

      <ul className="space-y-4">
        {docs.map((d) => (
          <DocCard key={d.slug} orgSlug={org.slug} doc={d} />
        ))}
      </ul>

      {org.role === "admin" ? (
        <UploadForm orgSlug={org.slug} onAdded={() => load(org.slug)} />
      ) : (
        <p className="text-muted-foreground text-sm">Only org admins can add docs.</p>
      )}
    </Page>
  );
}

function DocCard({ orgSlug, doc }: { orgSlug: string; doc: DocSummary }) {
  const [detail, setDetail] = useState<DocDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setOpen((o) => !o);
    if (detail) return;
    try {
      setDetail(await apiGet<DocDetail>(`/orgs/${orgSlug}/docs/${doc.slug}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <li>
      <Card>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <p className="text-strong font-semibold">{doc.title}</p>
              <p className="text-muted-foreground flex flex-wrap gap-x-4 text-sm">
                <span className="font-mono">{doc.slug}</span>
                <span>{doc.section_count} sections</span>
                <span>{kb(doc.chars)}</span>
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={toggle} aria-expanded={open}>
              {open ? "Hide" : "Read"}
            </Button>
          </div>
          {open && error && <p className="text-destructive text-sm">{error}</p>}
          {open && detail && (
            <div className="space-y-4 border-t pt-4">
              <div className="space-y-2">
                <p className="text-muted-foreground text-xs">
                  Sections a lesson can cite (anchor in mono):
                </p>
                <ul className="flex flex-wrap gap-2">
                  {detail.sections.map((s) => (
                    <li key={s.anchor}>
                      <Badge variant="cyan" title={s.heading}>
                        <span className="font-mono">{s.anchor}</span>
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
              <Markdown>{detail.content_md}</Markdown>
            </div>
          )}
        </CardContent>
      </Card>
    </li>
  );
}

function UploadForm({ orgSlug, onAdded }: { orgSlug: string; onAdded: () => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<DocDetail | null>(null);

  // A file only fills the text box: what's sent is what's shown, and an admin can fix it first.
  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setContent(await file.text());
    if (!title) setTitle(file.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " "));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setAdded(null);
    try {
      const doc = await apiPost<DocDetail>(`/orgs/${orgSlug}/docs`, {
        title: title.trim(),
        content_md: content,
      });
      setAdded(doc);
      setTitle("");
      setContent("");
      await onAdded();
    } catch (err) {
      setError((err as Error).message); // the draft stays in the form
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1">
        <h2>Add a doc</h2>
        <p className="text-muted-foreground max-w-[64ch] text-sm">
          Markdown or plain text with headings. Docs don&apos;t change once added, because courses
          are built on a specific version: to revise one, add it under a new title.
        </p>
      </div>
      <Card>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="doc-title">Title</Label>
            <Input
              id="doc-title"
              required
              minLength={2}
              maxLength={300}
              placeholder="e.g. Staging environment guide"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="doc-file">
              From a file <span className="text-muted-foreground font-normal">(optional)</span>
            </Label>
            <Input
              id="doc-file"
              type="file"
              accept=".md,.markdown,.txt,text/markdown,text/plain"
              onChange={onFile}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="doc-content">Content</Label>
            <Textarea
              id="doc-content"
              required
              rows={10}
              className="font-mono text-sm"
              placeholder={"# Title\n\n## A section\n\nWhat a lesson can cite…"}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>
      {error && <p className="text-destructive text-sm">{error}</p>}
      {added && (
        <p className="text-green-ink text-sm">
          Added “{added.title}”: {added.sections.length} sections can be cited.
        </p>
      )}
      <Button type="submit" disabled={busy}>
        {busy ? "Adding…" : "Add doc"}
      </Button>
    </form>
  );
}
