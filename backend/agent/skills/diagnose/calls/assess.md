Assess the learner's **demonstrated level** from their answers to the probe (§4.3).

- Judge **what the answers show**, not how fluent or confident they sound. A confident wrong answer is evidence of a gap. A hesitant correct answer is still evidence of knowledge.
- `assessed_level` uses the same scale as the claim: novice, intermediate, strong, expert.
- `evidence`: one entry per answer that drove your decision. Say what the answer showed (or failed to show) and which level it points to. Quote or paraphrase the answer.
- `gaps`: the specific concepts the answers show are missing or shaky. These shape the concept map.
- `confidence` (0–1): how sure you are, given only 3–4 answers. Blank or "I don't know" answers count as evidence of a gap. They don't lower your confidence.
- **If `assessed_level` differs from `claimed_level`, `adjustment_message` is required.** Write it to the learner in plain language: what they claimed, what the answers suggest, the specific answer that drove it, and what that means for where the course starts. Example: "You said intermediate, but your answer on connection pooling suggests we start a step earlier: you described the pool as a cache of query results. Here's why that matters…"
- If they match, `adjustment_message` is null. Don't congratulate.
