---
name: checkpoint
description: Close out a pair checkpoint (PC) or checkpoint (CP) in this repo. Runs the checks, does a privacy scan, updates BUILD_LOG/ADRs/roadmap/deck outline, commits, pushes, and posts the pair-checkpoint summary. Use whenever a PC or CP is finished.
---

# checkpoint

Run these steps in order. Stop and report if any step fails; never commit red. Chain the checks so a failure blocks the commit (`make lint && make test && git commit …`). Printing a failure isn't enough.

## 1. Checks
Run whichever of these exist (check the `Makefile`):
- `make doctor`: Postgres, Redis and `FT._LIST` are reachable
- `make lint`: ruff, plus ESLint/tsc for web
- `make test`: pytest, deterministic tests only
- `make evals`: only at CP boundaries from CP5 on; needs `ANTHROPIC_API_KEY`

## 2. Privacy and secrets scan (the repo is public)
- `git status --porcelain` must show nothing under `docs/private/`.
- `git diff --cached` must contain no keys. Grep the staged diff for `sk-ant-`, `ANTHROPIC_API_KEY=.+`, `-----BEGIN`, and `password=` with a real value.
- Grep the staged diff for each term in `docs/private/scan-terms.txt` (one regex per line, gitignored), e.g. `git diff --cached -U0 | grep -nE -f docs/private/scan-terms.txt`. Review every hit by hand. Public files must describe the product and how it's built, nothing personal.

## 3. Docs
- **At a CP boundary**, append a `BUILD_LOG.md` entry with these headings:
  - What we built
  - Key prompts
  - Decisions (link ADRs)
  - Where the AI went wrong or was corrected (be specific and honest)
  - Tradeoffs accepted
  - How to verify
- Any new non-obvious choice gets an ADR (use the `adr` skill).
- If any persisted data changed (Postgres tables/columns, JSONB shapes, Redis keys/types/TTLs/indexes, cookies or browser storage, or a new store), confirm that `docs/data-model.md`, the migration, the Pydantic schemas and the generated types are all updated (CLAUDE.md persisted-data rule).
- If a roadmap item moved phases, update `docs/roadmap.md`.
- If `docs/private/checkpoint-extra.md` exists (gitignored), follow its extra steps too.
- Keep the CLAUDE.md commands table current.
- **Always** update the status line at the top of `BUILD_LOG.md` (current CP/PC, branch, PR, next step) and the Status table in `docs/build-plan.md`. A new session resumes from them.

## 4. Commit and push
- Work happens on the CP branch (`cpN/<slug>`), never directly on `main`.
- Use Conventional Commits, e.g. `feat(agent): diagnose probe + llm_calls logging (PC1.1)`.
- End the message with the co-author line from the session's attribution instructions.
- `git push`, then wait for CI on the draft PR (`gh pr checks --watch`).
- **At a CP boundary:**
  1. Update the PR description: what was built, how to verify, decisions.
  2. `gh pr ready`.
  3. Once CI is green: `gh pr merge --merge --delete-branch`.
  4. `git switch main && git pull`.
  5. Create the next CP branch and open its draft PR.
- At CP6, after merging, also run `git tag v0.1.0 && git push --tags`.

## 5. Post the pair-checkpoint summary, then wait for "go"
- **Built:** 3–5 bullets.
- **Architecture now:** a Mermaid diagram with the new piece highlighted, only if it changed.
- **Your turn:** a small exact coding task, the file, and the test that must pass. Or "none this time".
- **Verify:** exact commands or clicks, and the expected result.
- **Check:** 2–3 questions about why it's built this way.
- **Next:** the next PC and why.
