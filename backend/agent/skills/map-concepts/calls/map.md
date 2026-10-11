Build the concept map for this learner (§4.4).

- **6–12 concepts.** `cram` mode: 6–8, must-knows for the goal only. `foundation` mode: as many as the goal and time need, up to 12.
- `id`: a short kebab-case slug (`connection-pools`). `title`: a few words.
- `mastery_statement`: one sentence starting "You can …" with an observable verb (explain, choose, diagnose, design…), specific to this topic. `objective_level` is the Bloom level of that verb. Early concepts can sit lower; the last ones should reach what `config.target_level` and `mission.expert_means` call for.
- `prereqs`: ids of **direct** prerequisites from this map only. No cycles. A concept with no prerequisite in this map has `[]`.
- `est_minutes`: realistic time for one lesson plus its quiz, 5–120. **They must add up to within ±15% of `target_minutes`** (computed for you in the input). Check the sum before answering; if it's off, change the estimates or the number of concepts.
- `concept_type`: algorithm, systems, math, syntax, api or conceptual. It decides what kind of hands-on prototype the lesson gets, so pick what the learner will actually manipulate.
- `sequence`: every concept id exactly once, each after all of its prereqs. Among concepts whose prereqs are met, put the assessment's gaps and the goal's must-knows first.
- `sequence_rationale`: 2–4 sentences to the learner ("you") on why this order: where it starts given their assessment, what the early concepts unlock, and how it ends at their goal. No praise.
