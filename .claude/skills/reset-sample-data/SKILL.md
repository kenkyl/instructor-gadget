---
name: reset-sample-data
description: Put the dev environment back to the known sample state (seeded org, users, docs, kyle's mid-course and completed courses, the Acme AI org course assigned to dana) and pre-generate its lessons. Use before a walkthrough, after manual testing has changed the data, or when asked to reset the sample data.
---

# reset-sample-data

1. **Check the ports and stores.** `make up` (Docker running), then `make doctor`: all four PASS, including the three indexes (`idx:llm_exact`, `idx:llm_semantic`, `idx:intake_guard`). If `make dev` is running, leave it: the reset doesn't need it stopped, but tell Kyle every browser session is logged out.
2. **Reset.** `make reset`. It migrates, wipes every app table (TRUNCATE, not DROP), deletes only `sess:*` and `dash:*` in Redis, re-seeds, and loads `backend/seed/sample.py`. Expect three ids printed (kyle's two enrollments, the org course).
   - Never `FLUSHDB`/`FLUSHALL`: on Redis 8 it drops every search index (ADR-0019 addendum). The LLM caches survive the reset on purpose.
3. **Warm.** `make warm-cache` (needs `ANTHROPIC_API_KEY`). First run on an empty cache: about 8 lessons, ~$0.20, ~35 s. After a reset with the cache intact: 7 exact hits and one regenerated remediation lesson (~$0.02, ~10 s). Report the printed lines and the cost.
4. **Verify** (`make dev`, then http://localhost:3000):
   - **kyle:** "Incident investigation fundamentals…" with 4/10 complete, "1 due for review", a red (shaky) cell; the plan shows v1 → v2 ("Re-planned after a quiz", insert remediation) and the misconception. "Redis data structures" shows Complete and "2 due for review".
   - **dana:** "Acme AI tech onboarding for new hires" (org course); opening "Request path" is served from cache in milliseconds.
   - **priya:** "Org courses you manage" lists the Acme course (Accepted, 1 assigned); Org impact shows the course.
5. If `make reset` fails with "Sample data is already loaded", something skipped the wipe: rerun `make reset` (it always wipes first) rather than `python -m seed.sample`.

Sample content lives in `backend/seed/sample/courses.yaml` (real model output: two maps exported from development runs, one generated for it) and the scripted score history in `backend/seed/sample.py`. Change the story there, then run `make test` (`tests/test_sample.py` checks it lands as described).
