# Walkthrough

The exact click path through the three journeys, from a clean sample state. Allow about 15 minutes; live model calls are marked with their typical wait.

## 0. Set up (once, ~2 minutes)

```bash
make up && make doctor        # all PASS, three indexes listed
make reset                    # wipe app data, re-seed, load the sample learner state
make warm-cache               # pre-generate the sample lessons (~35 s, ~$0.20; ~$0.02 when re-run)
make dev                      # API :8000, web :3000
```

Open http://localhost:3000. The login page lists the three seeded users; there are no passwords.

| User | Who | Starts with |
|---|---|---|
| **kyle** | An individual learner | "Incident investigation fundamentals for on-call engineers" (4 of 10 done, re-planned once) and a completed "Redis data structures" |
| **dana** | A new engineer at Acme AI (member) | "Acme AI tech onboarding for new hires", assigned, not started |
| **priya** | An Acme AI engineering manager (admin) | The Acme AI template she built and assigned |

The dashboard header says whether the page was **served from the Redis cache** or **rebuilt from Postgres** (cache-aside; any progress write deletes the key).

## 1. The dashboard and a course mid-flight (kyle)

1. **Continue as kyle.** Two courses:
   - The incident course: one cell per concept, coloured by mastery band, a ring on the one **due for review**, "1 due for review", and the band counts in words.
   - "Redis data structures" with the **Complete** badge and "2 due for review" (FSRS scheduled them).
2. Open the incident course. The plan shows the path, each concept's band, mastery and next review. One concept, **Liveness vs. readiness probes**, is shaky and locked; a remediation, **What a failing liveness probe actually does**, sits before it, and **Diagnosing probe-driven restarts** stays locked behind it.
3. **How the plan changed:** v1 (planned from the diagnostic) → v2 (re-planned after a quiz, rule `insert_remediation`), with the reason in plain English and the logged misconception ("liveness failure = out of the load balancer").
4. Open the remediation concept. Its lesson is already stored (warm-cache), so it opens instantly: a different angle on the same idea, aimed at the named belief.

## 2. J1: create a course (kyle, ~60 s of model time)

1. Dashboard → **New course**. Topic: `Kubernetes probes and rollouts` (any real topic works; a crude, off-topic or prompt-injection request is refused before anything is stored: the RedisVL intake guard).
2. Set **Your current level** to **Intermediate**, keep the defaults, **Create course** (~10 s: the diagnostic questions).
3. Answer like a novice, on purpose: e.g. "I'd restart it", "Not sure, I think they're the same", "More replicas should help". **Submit answers** (~6 s).
4. The assessment says, in plain words, that it is starting you at **novice** and why, quoting your answers. It never re-levels silently.
5. **Build my concept map** (~15 s): 6–12 concepts with prerequisites, a "You can …" mastery statement each, and a total time within ±15% of the target. Remove one concept: if others depend on it, you're warned first.
6. **Accept this map.** The course appears on the dashboard (rebuilt from Postgres, because accept deleted the cache key).

## 3. J2: learn, check, adapt (kyle)

1. Open the new course's first concept. The lesson **streams** in (~15 s): explanation (counterintuitive part first), a worked example, a Mermaid diagram. A database-pooling concept also shows the **connection-pool simulator** (sandboxed iframe): push the request rate up and watch latency stay flat, then explode past ~100% pool utilization.
2. **Take the quiz** (under "Check your understanding"): four multiple-choice questions and one short answer, no hints. For the "bad quiz", pick wrong options and write an answer that states a belief, e.g. *"A failing liveness probe takes the pod out of the load balancer."* **Submit answers** (~10 s of grading).
3. The result: the score (1–4), feedback that names the error and the underlying belief, the mastery band, the next review date, and **What happens next**: here a remediation concept inserted before this one (plan v2).
4. Retake with a good answer instead (a 3 or 4) to see **Advance** and the next concepts unlock; a 4 on a later concept can offer **Test out** of the next one.
5. A locked concept explains what you'd misread if you opened it early; **Open it anyway…** is allowed and logged.

## 4. J3: an org course grounded in docs

1. **priya:** dashboard → **Org docs**: the four Acme AI docs, each heading a citable section with an anchor. **Org courses you manage** lists the accepted template (1 assigned). Open it: the docs-grounded map, built with no probe, and the assign card with dana assigned. (**New course** → "Acme AI: a course for your team, grounded in your docs" → pick docs → **Create org course** → **Build the course template** builds another one in ~40 s.)
2. Log out, **continue as dana.** Her dashboard shows the course labelled as an Acme AI course. Open **Request path** (or the other open concept). It arrives in milliseconds: an **exact cache hit** from the warm-up, not a new generation. Every claim about Acme carries a numbered citation; each source shows the doc, the section and the verbatim quote (code checked the quote is really in that section). A concept the docs don't cover says so ("This isn't covered in your docs") instead of guessing; `make eval-grounding` shows that case.
3. **Trace** (header link): every model call dana's lessons made, with the cache result (exact hit, semantic hit, miss), latency and cost, and the impact tile: what the cache saved, measured from the original generation.
4. Log out, **continue as priya** → **Org impact**: calls, hit rate, dollars spent and saved across the org's courses, per course and per learner. Counts and dollars only, never a learner's answers.

## 5. The evals (terminal, ~70 s, ~$0.60)

```bash
make evals        # diagnosis personas, map constraints, pedagogy, grader vs. human labels, grounding judge, cache false hits
make eval-cache   # the semantic-cache threshold sweep (no API calls)
```

The last run is in [`backend/evals/results/`](../backend/evals/results/).

## Reset

`make reset && make warm-cache` puts everything back (the `reset-sample-data` skill does the same, with checks). The reset keeps the LLM caches and Redis indexes: it deletes only sessions and dashboards, and never runs `FLUSHDB`.
