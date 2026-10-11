---
name: new-instructor-skill
description: Scaffold a new Instructor product skill folder (backend/agent/skills/<name>/) in the standard shape and verify the registry loads it. Use for every product skill (diagnose, map-concepts, teach-concept, etc.) so they all follow one pattern.
---

# new-instructor-skill

Arguments: the skill name (kebab-case), plus its calls, each with a cache policy (`exact` | `semantic` | `never`) and whether it streams.

## Steps
1. Read `backend/agent/registry.py` and one existing skill folder. **The registry is the source of truth for the format**; if this file and the registry disagree, follow the registry and fix this file.
2. Create:
   ```
   backend/agent/skills/<name>/
     SKILL.md              # frontmatter + skill-level instructions
     calls/<call>.md       # one per call: what to produce, rules specific to this call
     schema.py             # Pydantic Input/Output per call; export CALLS = {"<call>": (Input, Output)}
     references/.gitkeep   # optional reference material (e.g. prototype patterns)
     evals/cases.yaml      # at least one case per call: input fixture + assertions
   ```
3. `SKILL.md` frontmatter:
   ```yaml
   name: <name>
   version: 0.1.0
   description: <one line: which spec section it implements>
   calls:
     <call>: { cache: never, stream: false, max_tokens: 2000 }
   ```
4. Instructions in `SKILL.md` must follow `docs/learning-design.md`. Cite the spec section each rule comes from. Never restate the shared conduct rules (`skills/_shared/conduct.md` is composed in automatically).
5. Cache policy: `diagnose`, `grade`, `remediate` and anything with learner misconceptions must be `never` (ADR-0007).
6. Validators belong in `schema.py` (e.g. "a message is required when assessed ≠ claimed"). Deterministic decisions belong in `pedagogy.py`, never in a skill.
7. Verify by running `uv run pytest backend/tests/test_registry.py`. The new skill must load, and its `prompt_version` must be printed.
