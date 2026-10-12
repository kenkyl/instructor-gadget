# Overview

## The problem

Most learning tools take your word for where you are, teach a fixed syllabus, and call it done when you've read it. People overestimate what they know, fluent rereading feels like understanding, and a course that never checks can't adapt. Instructor's rule: **understanding is demonstrated, not declared.** Mastery is only recorded from a graded retrieval attempt ([`learning-design.md`](learning-design.md)).

## The three journeys (Phase 1)

| | Journey | What happens |
|---|---|---|
| **J1** | Create a course | Intake (topic, goal, claimed level) → 3–4 diagnostic questions → an assessed level with the evidence, and a plain explanation when it differs from the claim → a concept map with prerequisites, a "You can …" mastery statement per concept and a time budget → the learner removes concepts and accepts. |
| **J2** | Learn, check, adapt | One concept at a time, gated on prerequisites being solid. A streamed lesson (explanation, worked example, diagram, sometimes an interactive simulator) → a zero-hint quiz (4 multiple choice + 1 transfer question) → a 1–4 grade with feedback that names the error → mastery, band and an FSRS review date → a rule-based adaptation (advance, offer a test-out, retake, or insert a remediation concept) recorded as a new plan version with the reason. |
| **J3** | Org course grounded in docs | An org admin picks internal docs and builds a course template from them, accepts it and assigns it. Learners' lessons cite the docs section by section with verbatim quotes, and say "This isn't covered in your docs" instead of guessing. The admin sees what the cache saved across the org, never what learners wrote. |

The dashboard shows each course's concepts coloured by mastery band, how many are due for review, and a badge on completion.

## Architecture in one paragraph

Next.js proxies `/api/*` to FastAPI. Services hold the rules and call an in-process agent package: a skill registry (prompts as versioned files), one LLM wrapper (validated structured output, one retry, every attempt logged), deterministic pedagogy in code, and grounding for org docs. Postgres is the source of truth. Redis 8 holds sessions, a cache-aside dashboard, an exact LLM cache, a RedisVL semantic LLM cache, and a RedisVL intake guard. The Anthropic API is the only external dependency; embeddings run locally. Details: [`architecture.md`](architecture.md).

## Key tradeoffs

- **Skills do language; code does decisions.** Scores, mastery, gating, adaptation and review scheduling are unit-tested functions, so the model can't quietly inflate a grade or skip a prerequisite.
- **Caching only what's safe to share.** Lessons and shared quizzes are cached; anything carrying a learner's answers or misconceptions never is. The semantic threshold was set by a labelled eval at zero false hits, accepting that only about a third of paraphrases are served.
- **Context stuffing, not RAG,** for org docs: the seeded doc set is ~10k tokens, the model sees whole sections, and citations are checked against the exact text it saw. Redis vectors are the upgrade path when doc sets grow.
- **Templates for org courses:** one admin-built map shared by a cohort (and cached across it), at the cost of no per-learner diagnostic for org courses in Phase 1.

## Known gaps

- The grounding judge isn't validated against human labels; its numbers are a smoke alarm, not a measurement.
- The grader agrees with human labels within one point every time, but exactly only about half the time (always scoring lower).
- Mastery constants and FSRS parameters are defaults, not tuned against outcomes.
- The intake guard judges subject, not intent: a chat-style question or smuggled code can pass.
- Org courses are docs-only; labelled outside knowledge is designed but not built.
- Review sessions, instructor chat, an MCP surface and deployment are later phases ([`roadmap.md`](roadmap.md)).

Try it: [`walkthrough.md`](walkthrough.md).
