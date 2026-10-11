The rule `rule` fired after the learner scored `score` (1–4) on `concept`. A remediation concept is being inserted before it.

- `why`: 2–3 sentences to the learner: the score, the specific belief from `misconceptions` (if any), and what was added and why it comes next. Example: "You scored 2 on Liveness vs readiness. You believe a liveness failure removes the pod from the load balancer; it restarts the container instead. I've added a short concept that attacks that from a different angle before you retake the quiz."
- `remediation_concept`: a short concept (about 10 minutes) aimed squarely at that belief.
  - `title`: specific, not "Review of X".
  - `mastery_statement`: starts "You can …", observable.
  - `angle`: one sentence on how it re-teaches differently from `lesson_explanation`.
