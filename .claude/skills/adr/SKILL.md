---
name: adr
description: Append a numbered architecture decision record to docs/decisions.md in the standard shape. Use whenever a non-obvious technical, product or pedagogy choice is made, including mid-checkpoint.
---

# adr

1. Read `docs/decisions.md` and find the highest `ADR-NNNN`. The new one is the next number.
2. Append this block, with each field kept to 1–3 sentences:
   ```
   ## ADR-NNNN: <short decision title>
   **Context:** <the problem or force>
   **Decision:** <what we chose>
   **Alternatives:** <the options considered, and why not>
   **Consequences:** <what this costs and what it enables>
   **One-liner:** <one sentence a listener could repeat back>
   ```
3. If the decision changes `docs/learning-design.md` or `docs/build-brief.md`, edit that doc too, and reference the ADR number there.
4. If it moves a roadmap item, update `docs/roadmap.md`.
5. Tell Kyle the ADR number and its one-liner.
