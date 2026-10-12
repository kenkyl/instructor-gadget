# Build log

> **Current status:** CP5 ✅ built, PR #7 ready for review (CI green). **CP6 ✅ built** (sample data, reset, warm-cache, docs, run-through) on `cp6/hardening`, draft PR #8 stacked on CP5. Next: Kyle merges PR #7 (merge commit); then retarget PR #8 to `main`, merge `origin/main` into `cp6/hardening` (no rebase), push, mark ready; Kyle merges; then `git tag v0.1.0 && git push --tags`.
> **Resuming in a new session:** read `CLAUDE.md`, this file, `docs/build-plan.md`, and `docs/decisions.md`, then start the next PC listed above. Load the `claude-api` skill before writing LLM code.

One entry per checkpoint. Each entry covers what we built, the key prompts and decisions, where the AI went wrong or needed correcting, and the tradeoffs we accepted.

---

## CP6: hardening, sample data, docs (Mon 2026-10-12, PR #8, stacked on #7)

**What we built**
- **PC6.1, sample state:** `make reset` wipes every app table (TRUNCATE), deletes only `sess:*` and `dash:*` (never FLUSHDB; the LLM caches and indexes stay), re-seeds, and loads `seed/sample.py`: kyle's "Incident investigation fundamentals for on-call engineers" at 4/10 with one concept due, a shaky concept with a logged misconception and a remediation (plan v1 → v2), a completed "Redis data structures" with its badge and 2 due, and the Acme AI template accepted and assigned to dana. Built through the real services (create, accept, assign) with every mastery, band and review date from pedagogy; `tests/test_sample.py` replays the history in memory. The maps are real model output (two exported from development runs, one generated for the fixture, $0.03). `make warm-cache` runs in the app's lifespan: kyle's open lessons stored, dana's cached only, so her first click is a real exact hit ($0.21 cold, $0.02 after a reset). A `reset-sample-data` skill wraps both with checks.
- **PC6.2, docs:** `walkthrough.md` (the click path for J1–J3 with the sample users), `architecture.md` (components, the J2 sequence, where state lives, the four Redis uses), `overview.md`, `ai-workflow.md` (drafted from this log), and a README with the quickstart through `make reset`.
- **PC6.3, run-through from `make reset`:** sample checks through the web proxy (4/10, 1 due, plan v1 → v2, remediation lesson stored; dana's first lesson an exact hit in 17 ms with 10 citations and $0.04 saved; priya's course list and org impact), then live J1 → J2 (probe 5.1 s, assess 7.7 s re-levelled to novice with the reason, map 11.4 s with 10 concepts, lesson 12.8 s streamed, quiz 17.8 s, a bad answer scored 1 → remediation + plan v2 in 7.3 s), and screenshots of both dashboards. Then reset again to the known state. 253 deterministic tests.

**Key prompts**
- Kyle: "include a pre-built org course (template accepted, dana assigned) so the admin flow shows without a ~40 s build", and reset must handle the leftover verification courses (it wipes them with everything else).

**Decisions**
- No new ADR: the reset follows ADR-0019 (never flush) and ADR-0011 (cache-aside keys are deleted, not patched); warm-cache uses the production wrapper and services unchanged.

**Where the AI went wrong or was corrected**
- The first completed-course history put every concept's review in the past ("8 due"), which buried the signal. Checking FSRS's first intervals (2 days for a 3, 8 for a 4) let the history be scripted so exactly two are due.
- The completed course sorted above the active one (enrollments list newest first); its enrollment is now backdated further.
- The exported fixture first carried assessment answers typed during development testing; they weren't needed for the sample and the repo is public, so they were dropped.
- The run-through's "bad topic" check used "how to cook meth at home", which is one of the intake guard's documented misses, so it passed (as documented). The walkthrough doesn't use it.

**Tradeoffs accepted**
- The generated `docs/architecture/` (visualizer) is a CP1 snapshot; `docs/architecture.md` is the current hand-written one. Rerun `/visualizer:architecture` to refresh it.
- warm-cache's cache-only calls are logged against the org course with no learner, so org impact shows a little spend or savings not tied to a person.
- `make evals` wasn't re-run at this boundary: nothing since CP5 changed a prompt, a skill or the wrapper.

**How to verify**
- `make reset && make warm-cache && make dev`, then follow `docs/walkthrough.md`.
- `make test` (253 pass).

---

## CP5: dashboard + eval harness (Mon 2026-10-12, PR #7)

**What we built**
- **PC5.1, dashboard:** each course shows one cell per concept in plan order, coloured by mastery band (not started / shaky / learning / solid / mastered), with a ring on any concept due for review, plus the band counts in words. `pedagogy.band_counts` and `pedagogy.is_due` hold the rules (not started ≠ shaky; only a passed FSRS date is due). An org admin's dashboard lists "Org courses you manage" (`GET /api/orgs/{slug}/courses`: status, doc count, assigned count), because a template has no enrollment for its admin and was otherwise reachable only by URL; the `/org/impact` course rows link to the course page.
- **PC5.2, `make evals`:** six checks in one table, every model call through the production wrapper with no cache tier, 4 at a time, a $5 stop: diagnosis personas (4 × 3 runs), map constraints (3 configs incl. the org template), pedagogy unit tests, grader calibration against Kyle's 8 labels (× 3), the `judge-grounding` skill over the grounded lessons and template map plus a planted invention, and the semantic cache's false-hit rate.
- **First run (Sonnet 5.5, $0.58, 47 requests, 69 s):** diagnosis within one level 12/12, consistent 3/4 personas; maps 3/3 valid; grader exact 13/24, within one 24/24, no restatement scored 4; judge 8/9 assertions, 0 invented org details, planted invention caught; cache false hits 0/15. Full report: `backend/evals/results/2026-10-12.md`. 251 deterministic tests.

**Key prompts**
- Kyle's CP5/CP6 plan: speed mode, no stops between PCs, CP6 stacked on CP5, live-eval spend pre-authorized to $5 with a cut order (personas first) that wasn't needed.
- Kyle's fold-in: the admin's org-course list, because nothing linked back to a template.

**Decisions**
- [ADR-0031](docs/decisions.md): `make evals` measures fresh generations through the wrapper; the grounding judge is a versioned product skill (`cache: never`) and is itself unvalidated.
- P1+ 1 (outside knowledge) will be ADR-0032, not 0031.

**Where the AI went wrong or was corrected**
- The dashboard already had the Complete badge, the due badge and a concept strip; the brief's "mastery bands per concept" was the only real gap. Checking first kept PC5.1 small.
- The grader disagreed with 11 of 24 labels, every time one point lower. Reading them, the disagreements trace to the labels vs. the item's own rubric (a2 is "right for the wrong reason", a 1 by §4.7; a5/a6 never address the 5,000-thread plan, the rubric's 2), not to the prompt. Left for Kyle rather than tuning the prompt to 8 answers.
- The accurate-intermediate persona came back intermediate once and strong twice: within one level, but the only inconsistent persona.

**Tradeoffs accepted**
- The judge uses the same model as the generator; validating it needs hand-labelled claims.
- `make evals` isn't in CI (cost, and it needs the key); its committed inputs are checked by `make test`.
- The dashboard now loads every progress row (for the strip) instead of SQL counts; fine at Phase 1 sizes and cached in Redis.

**How to verify**
- `make test` (251 pass, no API); `make evals` (~$0.60) prints the table above.
- Log in as priya: the dashboard lists "Org courses you manage"; `/org/impact` course titles link to the course page. As kyle, a course mid-way shows coloured cells and the band counts.

---

## CP4: J3, org course grounded in docs (Mon 2026-10-12, PR #6)

**What we built**
- **PC4.1, org docs:** four seeded Acme AI docs (service map, on-call runbook, a postmortem, how we ship); every heading outside a code fence becomes a citable section with a code-computed anchor; upload (admins), list and read; an org course draft is pinned to a doc set by hash and has no probe (ADR-0028).
- **PC4.2, grounding:** `ground-in-sources`, a modifier skill. The docs go first in the prompt with each section tagged by its anchor, and the grounding rules go last. Lessons and quizzes cite with `[n]` markers and `{doc, section, quote}`; code checks that every section exists and every quote is verbatim in that section, with the one retry on a failure. The composed docs' hash keys both cache tiers (ADR-0029).
- **PC4.3, template flow:** an org admin builds the course from the docs with no probe (a docs-grounded map starting at the cohort's level), edits it, accepts it, and assigns it. Each learner gets their own enrollment whose plan v1 is a copy of the template. The admin also gets an org-wide cache impact view: the trace's aggregate over every learner's calls, per course and per learner, with no excerpts (ADR-0030).
- **Numbers (live, seeded docs):** a template map of 10 concepts in 10.7 s for $0.034, valid on the first attempt; dana's first lesson streamed with 10 citations, every quote verbatim; the same lesson for a second learner was an exact hit in 24 ms, saving $0.041. 245 deterministic tests.

**Key prompts**
- Kyle's model plan: Sonnet for PC4.1 and PC4.3, Opus at medium effort for PC4.2 (the grounding design), with a reminder at each switch.
- The build brief's J3: an org course grounded in internal docs, with citations and an explicit "this isn't covered in your docs", turned into the rules in `ground-in-sources/SKILL.md`.
- Kyle after PC4.2, asking how confident the AI was of finishing PC4.3 and PC5 unattended. The answer split them: PC4.3 and the CP4 close yes; PC5 needs his merge first and an agreed eval budget.

**Decisions:** ADR-0028 (org docs are immutable; a course pins its set), ADR-0029 (our own citations with verbatim quotes, docs first, the composed docs' hash in both cache tiers), ADR-0030 (the template flow: a docs-only grounding mode for the map, accept enrolls nobody, assign copies the plan, org impact without excerpts).

**Where the AI went wrong or was corrected**
- **Found by Kyle verifying PC4.1:** the org course form kept the previous login's admin state, so dana still saw the scope selector (the API correctly refused her; the UI hadn't reset). Fixed on the branch, along with a leaked-semaphore warning at dev shutdown (tqdm's multiprocessing lock; a thread lock does the same job here).
- **Found by Kyle verifying CP4:** after logging out, the login page still showed "Signing in…" for the last user until a refresh. The same cause as the CP3 intake-page bug: Next 16 keeps the login page alive (hidden) after `router.replace("/")`, and its handler only reset `busy` on failure. Fixed by resetting before navigating; the other submit handlers were checked and already do.
- **PC4.2:** the first idea was the API's own Citations feature. Checking the docs showed it can't be combined with structured output (a 400), so citations became fields we validate ourselves, and a citation without its quote proved nothing (a valid anchor says nothing about the claim). A refactor of the citation checker left dead code after a `return`; a regex's `\1` pointed at the wrong group, so `` `a[3]` `` in inline code was rewritten as a citation (caught by a node run, fixed with an explicit pattern). The AI also staged Kyle's uncommitted grader labels by accident; unstaged, and left in his working copy.
- **PC4.3:** the first live run of the grounded map would have gone through the citation rules, which describe `citations` and `not_in_docs` fields a concept map doesn't have. The fix was a per-call grounding mode (`cited` or `docs`), not editing the modifier's text, so lesson and personal prompts kept their meaning. The first org-assignment test failed for a boring reason, a test that checked the personal prompt for the string `<documents>`, which the map's own instructions mention. Dev tooling stumbles: macOS has no `timeout`, BSD `sed -i` needs an extension, and `lsof -ti :8000 :3000` silently takes only one port, which left my dev servers running until a second pass stopped them (they were mine to stop). The test course I created in the dev DB was deleted afterwards so Kyle's walkthrough starts clean.

**Tradeoffs accepted**
- Grounding is checked by code for where a claim comes from (section exists, quote verbatim), not for whether the prose stays faithful. Per-claim faithfulness and "every concept is in the docs" are the CP5 grounding judge's job (`make eval-grounding` holds the cases).
- Docs are re-sent on every grounded call (~10k tokens, about 2¢ on Sonnet 5.5). API prompt caching on the docs prefix is a small follow-up.
- An accepted template can't be edited and a learner can't be un-assigned; build a new course (docs are immutable).
- The template map's concept → docs link isn't stored, so admins can't see coverage per concept.

**Kyle's ★:** done by the AI at Kyle's request (speed mode). Still open: label the 8 grader answers before CP5 (his labels are in his working copy, uncommitted).

**How to verify:** `make up && make migrate && make seed && make test` (245 pass), then `make eval-grounding` (~$0.15: two grounded lessons and a template map; expect citations with quotes, `not_in_docs` for Kafka lag, and 6–12 concepts drawn from the four docs). Then `make dev`: log in as **priya**, **New course** → Org course, tick the four docs, **Build the course template**, cut a concept, **Accept this template**, tick **Dana**, **Assign**. Log in as **dana**: the course is on the dashboard; open the first lesson and check the numbered sources. The "isn't covered" callout isn't reachable on demand in the app: the template map only holds concepts the docs teach (ADR-0030), so it appears only when a lesson needs a detail the docs omit. `make eval-grounding` (the Kafka lag case) and the grounding tests are where it is exercised. Back as priya, **Org impact**: assign priya too and open the same lesson to see an exact hit saving the first learner's cost. See "How to verify" in PR #6.

## CP3: Redis deep dive (Sun 2026-10-11, PR #4)

**What we built**
- **PC3.1, semantic tier:** RedisVL `SemanticCache` behind the exact tier in the LLM wrapper (exact → semantic → model), a local MiniLM vectorizer, and the ADR-0007 bucket as eight TAG pre-filters (skill.call, model, prompt version, org, level, formats, analogy, doc set), so a lesson can never cross an org or a learner preference however close the vectors are (ADR-0023).
- **PC3.2, cache eval:** `make eval-cache`, 12 should-hit and 15 should-miss labelled pairs through the real tier and filter, plus all 201 sibling-concept pairs from the dev DB's maps. Default threshold 0.12; intake guard 0.40 confirmed (ADR-0026). No model calls, ~6 s.
- **PC3.3, intake guard (added by Kyle):** a RedisVL `SemanticRouter` with block routes only rejects crude, off-topic, dangerous and injection course requests in ~10 ms, before anything is stored or sent to the model; fails open (ADR-0024).
- **PC3.4, trace + cache impact:** `/trace` (all courses or one; linked from the dashboard bar and each plan page) lists the learner's own calls with cache result, similarity, tokens, latency, cost and saved cost/time, under a cache impact tile (hit rate, calls avoided, $ and seconds saved, "the cache paid for N% of it") (ADR-0027). Stored quiz results now recompute "Next" and drop a stale test-out offer on read.
- **Numbers (live):** a paraphrased lesson request in a near-duplicate course was served by the semantic tier in 47 ms at similarity 0.889 (distance 0.111, the eval's prediction for that pair), saving $0.021 and 13.9 s against a 14 s miss. 181 deterministic tests.

**Key prompts**
- "Build the ★ yourself and explain it" (speed mode, PC3.1).
- Kyle, while verifying PC3.1: add an intake guard with a semantic router, block routes only, minimal code (PC3.3).
- "Labelled should-hit / should-miss pairs … sweep the threshold with the real model … use the dev DB's real data where useful" (PC3.2). The dev DB's real maps became the sibling check that set the threshold.

**Decisions:** ADR-0023 (semantic tier in the wrapper; the service supplies text and bucket), ADR-0024 (intake guard: block routes only), ADR-0026 (threshold 0.12 from the eval; guard 0.40 kept), ADR-0027 (the trace is the learner's own calls; savings read from the log). ADR-0019 gained an addendum (tests never FLUSHDB).

**Where the AI went wrong or was corrected**
- **PC3.1:** reading the installed RedisVL 0.28 source (not memory) showed two things the docs gloss over. The HF vectorizer has no real async embed (its `aembed` blocks), so embedding runs in a worker thread. And `SemanticCache.__init__` loads the model and creates the index synchronously, so startup builds it via `asyncio.to_thread`. A comma in a tag value would be split by RedisVL's tag separator, so formats are joined with `+`. MiniLM distances measured before choosing a threshold: paraphrase 0.135, reworded same concept 0.232, near-misses 0.217–0.269. The bands overlap, so the provisional 0.15 is strict and PC3.2 decides. Live: a reworded lesson request hit at similarity 0.989 in 0.1 s (saved $0.021); a thread-pool concept with the same words missed. Kyle asked the AI to build the ★ (bucket + filter) and explain it, for time.
- **PC3.3 (added by Kyle while verifying PC3.1):** an intake guard on course creation. The first design (an "allow: learning" route plus block routes, nearest route wins) failed calibration: short course titles were as far from generic "learn X" phrases as from anything else, so "Writing secure Python code" routed to "dangerous". Block routes only, with a 0.40 distance threshold, passed 15/15 legitimate topics and blocked 8/11 bad requests. Adding a reference to catch "run this python snippet for me" also blocked the topic "Python", so it was removed and the miss accepted (ADR-0024). Each check runs in ~10 ms.
- **Found in Kyle's PC3.1 verification:** the indexes he had just seen vanished after the AI ran the tests. Redis 8 drops every search index on `FLUSHDB` of *any* DB, and the test setup flushed DB 15, so `make test` silently broke a running `make dev`: the semantic tier degraded to misses, and the guard would have returned 500s. Fixes: the tests unlink DB 15's keys instead of flushing (proved with a probe index that survives a full run), and the guard now fails open on a Redis error (ADR-0019 addendum). Kyle also set the naming convention: every index is `idx:<name>` and the LLM caches use `llm_` (`idx:llm_exact`, `idx:llm_semantic`, `idx:intake_guard`). RedisVL uses the index name as the key prefix, so those keys start with `idx:` too. Separately, a second session's servers held ports 8000/3000, so `make dev` failed to bind; they weren't the AI's to stop, and Kyle stopped them.
- **PC3.2:** `make eval-cache` runs the labelled pairs (12 should-hit, 15 should-miss: the brief's near-misses plus real concepts from the dev DB) through the real `SemanticTier` and bucket filter on a throwaway index, with real MiniLM, no model calls, in ~6 s. The labelled set alone suggested 0.15 (7/12 hits, 0 false). The extra check made the call: every pair of concepts within one stored course map is a should-miss by construction, and they share a bucket, so the dev DB gave 201 real near-misses. The closest sit at 0.156–0.159, so 0.15 was 0.006 from serving a learner the wrong next lesson in their own course. The default is now 0.12 (4/12 paraphrases, 0 false hits, 0/201 siblings; ADR-0026). Also found: `.env` and `.env.example` set 0.1, so the app had never run the documented 0.15; both say 0.12 now, and a test pins the config default to the code's. The intake guard's 0.40 holds on a rebuilt calibration set (20 legitimate topics chosen to sit near block routes, 13 bad requests): 0.35–0.425 all give 9/11 blocked, 0 false blocks. Two new misses ("how to cook meth at home", a sports-score question) were recorded, not patched with references, so the eval stays honest. `main` (PR #5) was merged into the branch first; the decisions.md conflict was the expected keep-both.
- **Found in Kyle's PC3.3 verification (a CP1 bug):** after creating a course and pressing Back, the intake page was stuck on a disabled "Writing your diagnostic questions…" button. Next 16 with Cache Components hides pages in React `<Activity>` instead of unmounting them, so Back restores their state, and the submit handler never reset `busy` before `router.push`. Fixed as Next's own docs prescribe ("Resetting form state on submit"): reset in the handler before navigating. Also from that run: "Tell me about the weather in Seattle" passed the guard (0.488) because the legitimate topic "Weather forecasting models" sits closer to the weather references (0.46). Embeddings judge subject, not intent, so it was left as a known limit (Kyle's call); the probe turned it into a real climate course.
- **PC3.4:** running `npx prettier` on the new page also restyled two existing files (prettier isn't a project dependency); caught in `git diff --stat`, reverted, and only the intended lines re-applied. The first impact tile derived its "of N lookups" denominator from the hit rate on the client; replaced with a `lookups` field from the API.

**Tradeoffs accepted**
- With MiniLM the semantic tier is conservative: ~a third of genuine paraphrases hit at the safe threshold. Safe reuse comes mostly from the exact tier and the bucket; a stronger embedding model would need Kyle's OK and the same eval (ADR-0026).
- The intake guard judges subject, not intent: smuggled code, chat-style questions and some bad requests ("how to cook meth at home") pass. The model's conduct rules are the backstop; an intent flag on the probe call is deferred (ADR-0024, build plan).
- The trace shows only the learner's own calls; the org-wide "cost per learner falls" view waits for CP4's admin flow (ADR-0027).
- Abandoned lesson streams still aren't logged, so the trace shows completed calls only.

**Kyle's ★:** PC3.1's ★ was done by the AI at Kyle's request. Still open from CP2: label the 8 grader answers before CP5.

**How to verify:** `make up && make migrate && make seed && make test` (181 pass), then `make eval-cache` (prints the sweep tables). `make dev`, log in as kyle, open the first lesson in two near-duplicate courses, then **Trace** in the top bar: the second shows a semantic hit with its similarity and savings. See "How to verify" in PR #4.

## CP2: Learn, check, adapt (Sun 2026-10-11, PR #3)

**What we built**
- **PC2.1, pedagogy rules:** `agent/pedagogy.py`, pure and unit-tested: MCQ score, the lower-of-two combine, recency-weighted mastery (ADR-0005), bands, the unlock gate, and day-scale `fsrs` scheduling (ADR-0018).
- **PC2.2, streamed lessons + exact cache:** `teach-concept` streamed over SSE field by field (partial JSON → `field_delta`), the exact-match cache (`llm:exact:*` native JSON + `idx:llm_exact`, hits logged with saved cost and time), Mermaid rendered in a fully sandboxed iframe (ADR-0019, ADR-0020).
- **PC2.3, seeded prototype:** a connection-pool exhaustion simulator (`backend/seed/prototypes/conn-pool-sim.html`, seeded by `make seed`). Event-driven Poisson arrivals, exponential query times, a FIFO wait queue with a checkout timeout; it shows status, utilization, queue, p95 wait and 5xx rate, with spike and slow-query presets. It's shown in `<iframe sandbox="allow-scripts" srcdoc>` on lessons whose concept is about connection pools, for hands-on learners. Checked against queueing theory (Erlang C): p95 wait is ~50 ms at 85% utilization, ~0.5 s at 95%, and timeouts past 100%.
- **PC2.4, quiz + grading:** `design-assessment` (4 transfer MCQs, each distractor tagged with the belief it represents, plus an explain item with a rubric; keys, tags and rubric never leave the server before submission), `grade` (1–4; a 4 requires transfer, enforced by a validator), the shared vs targeted quiz split (ADR-0021), misconception logging from picked distractors and the grader.
- **PC2.5, adaptation:** `pedagogy.adapt` (the branch table), remediation inserted as a new prerequisite (ADR-0022), `remediate` (`explain_change` writes the why and the remediation concept, `lesson` streams its lesson, never cached), plan versions with a diff and a why, and the plan-history UI.
- **PC2.6, gate + test-out:** override with an LLM-written, specific warning (logged, a plan version), test-out after a 4 (a plan version; the next concept's quiz without its lesson, ADR-0006), course completion, and 8 draft grader answers for Kyle to label (`backend/evals/grader_calibration.yaml`).
- **Numbers (live, one learner, end to end):** lesson first text 1.3 s, full lesson ~13 s ($0.02); quiz design 17–24 s ($0.035, the slowest call, so it's prefetched while the learner reads); grading 2.4–3 s; a bad attempt → remediation + why in 9 s. A full J1 + J2 pass (course, 3 lessons, 5 quizzes, 3 grades, remediation, override) cost about **$0.27**. 158 deterministic tests.

**Key prompts**
- "We're speeding up for time. Skip my turn, do it yourself, verify, then give me brief answers to the check questions." The AI wrote the PC2.1–PC2.5 ★ pieces against the pre-written tests; Kyle's open ★ is labelling the 8 grader answers.
- "Build out up to CP3, then give me a summary and steps to test." PC2.3–PC2.6 were built and verified live in one pass.

**Decisions:** ADR-0018 (day-scale FSRS), ADR-0019 (search indexes on DB 0), ADR-0020 (SSE `no-transform`), ADR-0021 (shared vs targeted quiz calls), ADR-0022 (remediation as an inserted prerequisite; only structural changes version the plan).

**Where the AI went wrong or was corrected**
- **PC2.1:** checking the installed `fsrs` 6.3.2 source (not memory) showed its defaults are flashcard-scale (1 min / 10 min steps). A Good first quiz would have been "due" 10 minutes later. Fix: a day-scale scheduler (ADR-0018). `Band` moved to `agent/types.py` so `agent/` never imports `app/`. CLAUDE.md, the checkpoint skill and the build plan now say Kyle merges PRs. Kyle skipped the ★ to save time, so the AI wrote `mcq_score`/`combine`/`update_mastery`/`band` against the pre-written tests. Pyright caught a dict literal inferred as `int` instead of `Score`, so the mapping became a typed `MCQ_TO_SCORE` table.
- **PC2.2:** the build plan's "check SSE through the Next rewrite" step paid off. The stream was measured live through `:3000` with a gzip-accepting client: 332 events arrived in **one burst at 13 s**. Without gzip, Next streamed fine (first event 1.5 s). The cause was Next's compression, not the proxy; `Cache-Control: no-transform` fixed it (ADR-0020). Live numbers: a lesson miss took 12.3 s and cost $0.019, with first text at 1.3 s. An exact hit took 0 ms and logged $0.019 / 12.3 s saved. Other findings:
  - **Redis 8 only indexes DB 0** (`Cannot create index on db != 0`), so tests can't build `idx:llm_exact` on DB 15 (ADR-0019).
  - **A test-isolation trap:** importing `tests.conftest` from a test module ran it twice, so `DATABASE_URL` became `instructor_test_test`.
  - **Running pytest during a live check** wiped the live test-DB state (pytest recreates the DB and flushes DB 15), so the live setup had to be redone.
  - **A CP1 bug:** with `cacheComponents` on, Next 16 errors on `useParams()` outside `<Suspense>`. It was in CP1's course page too (the page still returned 200), and all three dynamic pages now wrap their client component in `<Suspense>`.
  - **Dependencies:** Kyle approved `mermaid` and `react-markdown`. Partial JSON parsing uses `pydantic_core.from_json`, so the backend has no new dependency.
- **PC2.4, a prompt bug that only a live run showed:** the first live quiz's explain item said "apply it to the situation described", but the situation lived in `transfer_situation`, which the learner never sees. The 4-point rubric expected numbers (12 cores, 40 ms) the learner couldn't know, so a 4 was impossible. The fake-LLM tests passed. Fix: the skill now says the learner sees only `prompt` and options, every prompt is self-contained, and the rubric may only expect facts the prompt gives. Re-run live: the explain prompt carried every number.
- **PC2.4, the AI's own test fixture was wrong:** a test retook a remediation quiz with an untargeted quiz, but the picked distractors had already logged beliefs, so the service correctly chose `design_targeted` and the fixture failed its validator. The test was fixed, not the code.
- **Caught in Kyle's walkthrough, missed by the AI's tests and live run:** Kyle overrode a locked concept, then failed it. The inserted remediation took the concept's unmet prereqs, so it sat locked behind the gate Kyle had already skipped, while the failed concept stayed open (plan v3's diff had no status change). The fix: a remediation for an overridden concept inherits the override (ADR-0022), with a regression test. The AI had tested override and remediation separately, never together.
- **Shell slip during live checks:** a zsh loop variable named `path` clobbered `PATH`, so a whole verification loop printed "command not found". Renamed and rerun; nothing else was affected.

**Tradeoffs accepted**
- Quiz design is slow (~20 s). It's prefetched after a fresh lesson, not streamed. The stored question set only appears whole.
- The grader's misconception plus every picked distractor's belief are all logged, so a 0/4 attempt can log five beliefs. Noisy, but it gives targeting the most material; resolution tracking is P2.
- Unlocks and completions aren't plan versions (ADR-0022).
- The override warning is echoed back by the client (build plan, known follow-ups).

**Kyle's ★:** PC2.1 and PC2.3/2.5 ★s were done by the AI at Kyle's request (time). Open: label the 8 grader answers before CP5.

**How to verify:** `make up && make migrate && make seed && make test` (158 pass). Then `make dev`, log in as kyle, and follow "Test J2" in the PR description.

## CP1: Create a course (Sun 2026-10-11, PR #2)

**What we built**
- **PC1.1, LLM client wrapper + probe + intake:** `agent/llm.py` is the only way to call the model: structured output via `output_config.format`, Pydantic validation, one retry with the errors (`_shared/retry.md`), server-side refusal fallback, and one `llm_calls` row per API request, written in its own transaction through a `CallSink`. `diagnose.probe` end to end (idempotent), plus the intake form with recommended defaults.
- **PC1.2, assess:** answers on one screen → assessed level, evidence per question, gaps, and a plain adjustment message. The input is passed as validation context (ADR-0015), the assessment is final (ADR-0014), and answers are treated as evidence, never instructions.
- **PC1.3, concept map:** the `map-concepts` skill, and `agent/plan.py` pure graph rules (unknown prereqs and cycle detection by Kyle; order; ±15% time in integer math) running as `ConceptMap` validators, so a bad map earns one re-ask. The map is stored as the course's base map (ADR-0016).
- **PC1.4, edit + accept:** cutting a concept rewires its dependents (ADR-0017). Accept creates the enrollment, plan v1 and `concept_progress` in one transaction (`pedagogy.initially_unlocked`), then invalidates the dashboard. Dashboard cards link to the course.
- **Numbers (live, end to end):** intake → accepted map = **24.5 s of LLM time** (probe 5.8, assess 6.5, map 12.2; target < 90 s) and **$0.045 per course**. The over-claimer was re-levelled with a specific reason. 70 deterministic tests.

**Key prompts**
- "Resume the Instructor build… Load the claude-api skill before writing any LLM code." Loading it is what exposed the forced-tool-use 400 before any code depended on it.
- "On verify step 1: should we fix this?" (9 high npm advisories). The AI traced all 9 to one unpatched `braces` advisory in dev-only tooling, where npm's "fix" is a breaking downgrade. Kyle chose no change.
- "I see two entries, but I refreshed twice." This exposed AI test data left in the dev DB. Live checks now use an in-memory sink or the throwaway test DB.
- The cut-a-prerequisite question (rewire / drop edge / cascade): Kyle chose rewire (ADR-0017).
- "I added an arch diagram via visualizer in another session and want to keep it in this PR." Kept as a generated artifact, not hand-edited.

**Decisions:** ADR-0013 (structured outputs, own validation), ADR-0014 (the assessment is final), ADR-0015 (input as validation context), ADR-0016 (`template_plan` is every course's base map), ADR-0017 (rewire on cut).

**Where the AI went wrong or was corrected**
- **AI mistake (PC0.6 verify step):** the AI told Kyle to edit a prompt file and re-curl `/api/skills`. The hash didn't change, because the registry is cached at startup and `fastapi dev` only reloads on `.py` changes. Fix: `make api` now runs uvicorn with `--reload-include '*.md' --reload-include '*.yaml'`, so prompt edits hot-reload in dev.
- **AI mistake (while testing that fix):** the AI started a test server on port 8001 without checking whether the port was free. It was in use by an unrelated local process, and the AI's cleanup (`kill` on whatever listened on 8001) stopped that process. Rule: check that a port is free before using it, and only kill PIDs the AI itself started.
- **PC1.1, plan vs. current API:** the plan said "structured output via forced tool use". Loading the `claude-api` skill before coding showed that current models (Sonnet 5.5, our default) reject forced `tool_choice` with a 400, and that `messages.parse()` raises on invalid output, losing the text and usage we log. The wrapper uses `output_config.format` and validates with Pydantic itself (ADR-0013). Checking the docs first avoided building on a dead API.
- **AI near-miss (PC1.1):** the registry loads `schema.py` by file path, so a normal `import agent.skills.diagnose.schema` would have created a second `ProbeOutput` class, and the wrapper's `isinstance`/contract checks would have failed at runtime. Caught while writing the service; the registry now shares one module via `sys.modules` (checked in both import orders).
- **AI mistake caught by a test (PC1.1):** `POST /courses/{id}/probe` returned 503 ("LLM not configured") to a user who doesn't own the course, because FastAPI resolves dependencies before the handler body. Ownership is now a dependency declared before `LlmDep`, so 401 → 404 → 503 is the order.
- **Process hygiene (PC1.1):** the AI verified that port 8765 was free before starting a test API. `pgrep` matched both the `uv` wrapper and its Python child, so the first `kill` failed harmlessly. The AI checked both command lines before stopping them. Nothing else was touched.
- **AI mistake (PC1.1 verify step):** the Verify step said "your call shows `ok`", but Kyle saw two rows. The second was the AI's own end-to-end test course, left in the dev DB without saying so. Rule: any live test data the AI creates is called out in Verify, or goes in-memory or under a throwaway user (PC1.2's live runs used an in-memory sink).
- **PC1.2, the prompt failed live runs that fakes would have passed:** the three `assess` eval cases (over-claimer, prompt injection, under-claimer) passed their asserts on the first live run, but reading the outputs showed three problems. The model promised a reassessment the product doesn't offer (→ ADR-0014). It listed untested topics as "gaps". And it said "start at intermediate" for a learner assessed *strong* (it mixed up the starting level with the target level). Each fix was one prompt line, re-run live. Lesson: asserts check the fields; a human still has to read the words.
- **AI mistake caught by its own test (PC1.3):** `time_error` used floats, and `180 * 1.15 == 206.99999999999997`, so a map at exactly +15% would have been rejected and sent for a pointless re-ask. Now integer math.
- **AI near-miss (PC1.3):** the AI wrote a developer note about cache policy into `SKILL.md`'s body, which is sent to the model as instructions. Moved to a YAML comment; the `new-instructor-skill` skill now warns about it.

- **AI near-miss (PC1.4):** a new test asserted kyle's dashboard was empty before accept, which only held because of test order. Caught on review and rewritten to filter by the course under test.

**Tradeoffs accepted**
- `diagnose` and `map-concepts` are never cached: about 4.5¢ and 25 s per new course, in exchange for never serving one learner's diagnosis to another. Revisit `map-concepts` for org templates (CP4).
- Generated maps chain early concepts more linearly than they need to. Noted as a CP5 judge ("is each prereq a real dependency?"), not fixed by prompt guesswork now.
- Probe idempotency is check-then-insert (a true double-POST race could make two calls); the UI fires it once.
- Draft courses aren't listed on the dashboard until accepted.
- npm audit: one unpatched advisory in dev tooling, left as is (Kyle's call).

**Kyle's ★:** `find_unknown_prereqs` + `find_cycle` (iterative three-state DFS), plus an extra test the AI missed: a path *into* a loop must be trimmed from the reported cycle.

**How to verify:** `make up && make migrate && make seed && make test` (70 pass). Then `make dev` → log in as kyle → New course → answer the probe badly → see the re-level message → Build my concept map → remove a concept that others need (warning, then rewire) → Accept → the course appears on the dashboard.

## CP0: Foundations (Sat 2026-10-10 → Sun 2026-10-11, PR #1)

**What we built**
- **PC0.1, repo foundations:** public repo (PolyForm Noncommercial), a product-only brief, roadmap, ADRs, CLAUDE.md, build skills (`checkpoint`, `adr`, `new-instructor-skill`), and private material kept in gitignored `docs/private/`.
- **PC0.2, data stores:** Postgres 16 + Redis 8.10 in Docker (bound to localhost, with healthchecks), plus `make doctor`, which proves the Query Engine is present via `FT._LIST`.
- **PC0.3, app wiring:** FastAPI (lifespan-managed async engine + Redis) behind a Next.js 16 `/api` rewrite, `/api/health`, OpenAPI → TypeScript types, and CI (ruff, pytest against real stores, OpenAPI drift check, eslint, tsc).
- **PC0.4, data model:** 15-table async SQLAlchemy model, with per-learner state on `enrollments` (ADR-0004). The first Alembic migration, an idempotent seed (Acme; kyle, dana, priya), an isolated `instructor_test` DB, and `alembic check` in CI. `docs/data-model.md` was written by a forked subagent.
- **PC0.5, login:** seeded-user login, sessions as a Redis **hash** with TTL (atomic `MULTI/EXEC`), an opaque HttpOnly cookie, `get_current_user` as the single auth seam, and a native-**JSON** dashboard cache-aside (ADR-0011). On the web side: Next `proxy.ts` (optimistic cookie check), login, dashboard, status pages, and shadcn/ui.
- **Between PCs:** branch-per-CP with draft PRs, and `main` protected (PR + passing checks). Pyright (standard mode) plus pytest failing on un-awaited coroutines (ADR-0012).
- **PC0.6, skill registry:** `agent/registry.py` discovers and strictly validates skill folders, enforces the never-cache list, composes conduct + skill + call (+ grounding) prompts, and computes `prompt_version = name@semver+sha8`. Includes the `diagnose` skill scaffold (probe + assess contracts and validators), `/api/skills`, and fail-fast loading at startup. **16 tests.**

**Key prompts**
- Planning: "Follow §0 of the brief and reply with everything in §11", then add pair programming, a public repo, best practice, and a license.
- "Let's make a feature branch for continued work if it makes sense", which led to branch-per-CP with draft PRs and branch protection.
- "Use the Redis native JSON data type instead of serialized strings… if you disagree, tell me." The AI partly disagreed: a hash for sessions, JSON for documents (ADR-0011).
- "Any rules added should capture schema changes elsewhere… and any data stores that could eventually be added," which became the persisted-data rule in CLAUDE.md.

**Decisions:** ADR-0010 (schema conventions), ADR-0011 (Redis types by access pattern), ADR-0012 (two safety nets for a missing `await`).

**Where the AI went wrong or was corrected**
- **CI action tag:** CI referenced `astral-sh/setup-uv@v10`, but that action publishes no floating major tag. Now pinned to `v10.3.0`.
- **Swallowed health-check errors:** the health check used `except Exception: pass`. During Kyle's ★ task, a typo and a misplaced `.scalar()` were swallowed and reported as "Postgres: error" while Postgres was healthy. Checks now log the exception.
- **Old Alembic template:** Alembic's generated migration failed our own lint rules (old `typing` imports). The template is fixed so future migrations come out clean.
- **Deprecated SQLAlchemy call:** SQLAlchemy 2.1 deprecated `Result.tuples()`. The AI used it from older-version habit, and the deprecation warning caught it.
- **Unverified dependency:** shadcn init added an unfamiliar `cn` dependency. The AI checked that it's shadcn's own package (repo shadcn-ui/cn, MIT) before accepting it.
- **Commit on a failing lint:** the AI's commit script ran `make lint`, which failed, but didn't stop, and committed anyway. CI caught it. Fix: checks now gate the commit (`make lint && make test && git commit`).
- **Overclaim about pyright:** the AI said pyright would catch Kyle's missing `await`. Tested in PC0.6, it didn't: redis-py types its commands as `Awaitable[int]`, not as coroutines. Fix: pytest now fails on "coroutine … was never awaited" (ADR-0012), proven with a throwaway failing test.
- **Unfounded data-model details:** the forked subagent's data-model doc stated a few details that hadn't been decided yet (cache TTL, cookie flags). They were reconciled against the code in PC0.5.

**Kyle's ★ tasks**
- **PC0.3:** added `postgres_version` end to end (failing test → model → endpoint → `make types` → UI). `tsc` caught the stale types.
- **PC0.4:** used `psql` to show the scope check rejecting a bad course, and that string enums accept invalid values (the ADR-0010 tradeoff), which the seed repaired.
- **PC0.5:** implemented `invalidate_dashboard`. The first attempt was missing `await`, and the test caught it.

**Tradeoffs accepted**
- String enums: easy to evolve, but not enforced by the DB.
- JSONB for shapes that are still evolving.
- Server-side sessions: one Redis lookup per request.
- Delete-not-patch cache invalidation.
- Redis-py `await` bugs are caught at test time, not statically.

**How to verify:** `make up && make migrate && make seed && make doctor && make lint && make test`, then `make dev`, open http://localhost:3000, log in as kyle and check the "served from cache" badge. `/status` shows the stack health, and `/api/skills` lists `diagnose` with its prompt versions.

---

## Planning: Sat 2026-10-10

**What we did**
- Wrote the build brief and the learning-design spec in a separate Claude project, then started Claude Code (Opus 5.5) in plan mode pointed at both.
- Claude replied with clarifying questions, a stack recommendation, a repo layout, a refined data model, the API, Pydantic sketches of the skill contracts, and a checkpoint plan with time estimates.
- Two more rounds of plan revision before approval (below).

**Key prompts**
- "Read docs/build-brief.md and docs/learning-design.md in full. Follow §0 of the brief and reply with everything in §11. Don't write any code yet."
- Second round: make the repo public, show a Mermaid architecture diagram before sign-off, run the build as **pair programming** with frequent review checkpoints, follow current best practice, relax the time box, and plan a Google Slides deck alongside.
- Third round: choose a license that stops others from monetizing the project.

**Decisions** (ADR-0001 to ADR-0009 in `docs/decisions.md`)
- Python/FastAPI + Next.js. A hand-rolled agent on the Anthropic SDK. The product-skills architecture.
- Enrollments (per-learner plans), with org courses built as admin templates.
- Recency-weighted mastery. Test-out instead of skip.
- Cache scoping. Async stack + Alembic. PolyForm Noncommercial license.

**Where the AI went wrong or was corrected**
- **Missed in the first plan:** it optimized for speed. The user redirected to pair programming, so they'd understand and be able to explain every component. The first plan had no checkpoints for learning or review.
- **Caught by the AI:** two conflicts inside the spec. The mastery formula contradicted the "a 3 means solid" rule, and "skip on a 4" contradicted "mastery only from graded retrieval". Both went to the user as questions instead of being silently resolved.
- **Caught by the AI:** a caching gap in the brief. Analogy domain and per-learner assessment were inputs to lesson generation but not part of the cache bucket, which would have served personalized lessons to the wrong learners.
- **Blocked by the safety classifier:** the AI tried to build a mermaid.live link to render the diagram; the auto-mode classifier blocked it as a public upload. That was the right call, and the diagram was shown inline instead.
- **Caught late by the AI:** planned to commit the brief verbatim until the public-repo decision. It contained personal planning notes, so a product-only copy is public and the original moved to a gitignored `docs/private/`.

**Tradeoffs accepted**
- Two languages (Python + TS), in exchange for RedisVL and local embeddings. Generated types limit the cost.
- A stricter, slower mastery path (test-out, never skip), in exchange for honest mastery.
- Source-available rather than OSI open source, in exchange for keeping commercial rights.
