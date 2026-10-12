# How we ship: PRs, CI and deploys

How a change goes from a branch to production at Acme AI. Every service in the inference platform follows this path, with the same checks and the same rollback.

## Principles

- Small changes, often. A PR over 400 changed lines needs a reason in its description.
- `main` is always deployable. If it is not, fixing it comes before any new work.
- Every deploy can be undone in minutes, and the person who ships it is the one watching it.

## Opening a pull request

1. Branch from `main`. Name it `<your-handle>/<short-description>`.
2. Keep one concern per PR. Refactors and behaviour changes go in separate PRs.
3. Fill in the PR template: what changed, why, how you tested it, and how to roll it back.
4. Mark it ready only when CI is green. Use a draft PR for early feedback.

## Review

- Every PR needs one approval from a code owner listed in `CODEOWNERS` for the paths it touches.
- Reviewers aim to respond within one business day. If you have waited longer, ask in your team's channel.
- Changes to database migrations, authentication or rate limiting need a second approval.
- Authors resolve every comment, or reply with why not, before merging.

## Continuous integration

CI runs on every push to a PR and must pass before merging.

| Stage | What it runs | Typical time |
|---|---|---|
| Lint and types | Formatters, linters, type checks | 1 min |
| Unit tests | Service tests with no external dependencies | 3 min |
| Integration tests | The service against Postgres, Redis and Kafka in containers | 8 min |
| Build | Container image, tagged with the commit SHA | 4 min |
| Security scan | Dependency and image vulnerability scan | 2 min |

A flaky test is a bug. Do not retry CI until green: open a ticket tagged `flaky-test` and quarantine the test in the same PR.

## Merging

- Use squash merge. The PR title becomes the commit message, written as `service: what changed`.
- Merging to `main` starts a deploy to staging automatically.

## Deploying

Production deploys are progressive and automatic once staging is healthy.

1. **Staging.** The new image runs the smoke suite against staging. A failure stops the pipeline.
2. **Canary.** 5% of production traffic goes to the new version for 15 minutes. The pipeline compares error rate and p99 latency with the old version and stops on a regression.
3. **Rollout.** 25%, 50%, then 100%, with a 5-minute pause between steps.

Release names look like `2026.03.10-2`: the date, then the day's deploy number.

### Deploy freeze

No production deploys after 15:00 UTC on Fridays, and none during an open SEV1. A change that fixes the incident is the exception and is deployed with the incident commander's agreement.

## Rolling back

- To undo a deploy, run `kubectl -n inference rollout undo deployment/<service>`, or revert the PR and let the pipeline ship the revert.
- Rolling back is always allowed. You do not need approval, and you do not need to find the cause first.

## Database changes

- Migrations are applied before the code that needs them, and must work with both the old and new code (expand, then contract).
- Never drop or rename a column in the same release that stops using it. Wait one full release.
- Test the migration on a copy of staging data. A migration that holds a lock for more than 5 seconds needs a plan reviewed by the data platform team.

## Feature flags

Risky behaviour ships behind a flag, off by default. Turn it on for internal traffic, then 5% of customers, then everyone. Remove the flag within two releases of reaching 100%.
