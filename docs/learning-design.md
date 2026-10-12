# Instructor: Learning Design Spec

**Status:** this is the source of truth for how Instructor teaches. The product's agent skills (§10) implement it. When code or prompts disagree with this doc, fix one of them deliberately and log the decision in `docs/decisions.md`.

**Inspiration and credit:** the `deep-learn` Claude skill (an interactive single-learner tutor) shaped the core loop: diagnose first, prerequisite-ordered concepts, zero-hint quizzing, misconception tracking, and spaced review. This spec is our own design. It extends those ideas to a multi-user, org-aware product and adds learning-science principles the skill doesn't cover (sources in §12).

---

## 1. Core principle

> **Understanding is demonstrated, not declared.** A concept counts as known only after a graded attempt to retrieve and apply it. Never because the learner said "makes sense", and never because they finished reading.

This is the difference from the click-next-video model of most course platforms, and it's the product's main claim.

## 2. Principles and the mechanics that implement them

| Principle | What it means | Mechanic in Instructor | Phase |
|---|---|---|---|
| **Retrieval practice** (testing effect) | Pulling an answer from memory builds retention far more than re-reading | Every concept ends in a graded quiz; reviews are quizzes, not re-reads | P1 |
| **Desirable difficulty** | Struggle during practice is where learning happens | First attempts get no hints. Explanations come *after* a graded attempt. | P1 |
| **Transfer over recall** | Real understanding survives a new context | Quiz questions use situations not used in the lesson | P1 |
| **Mastery learning / prerequisites** | Don't build on a weak foundation | Concept map with prerequisites; dependents unlock only when prereqs are solid | P1 |
| **Specific, corrective feedback** | "Close" teaches nothing | Wrong answers get the specific error *and* the misconception underneath it, which is logged | P1 |
| **Learning objectives with levels** | "Know X" is untestable | Each concept has a mastery statement tagged with a level: remember, understand, apply, analyze, evaluate, create | P1 |
| **Worked examples → faded practice** | Novices learn faster from worked examples, then from progressively less support | Lessons include a worked example. Faded (partially completed) practice items come in P2 | P1 → P2 |
| **Self-explanation / elaboration** | Explaining in your own words deepens encoding and exposes gaps | An optional "explain it in your own words" short-answer question, graded on the rubric | P1 |
| **Cognitive load management** | Working memory is small | One concept at a time; lead with the counterintuitive part; diagrams carry structure so the prose doesn't have to | P1 |
| **Spacing** (forgetting curve) | Without review, most of a session fades within days | FSRS scheduling per learner per concept; the dashboard shows what's due | P1 (schedule) → P2 (review sessions) |
| **Interleaving** | Mixing related concepts in practice improves discrimination between them | Review sessions mix due concepts instead of blocking them | P2 |
| **Calibration / metacognition** | Learners misjudge what they know | Learner rates confidence before answering; we track over- and under-confidence | P2 |
| **Personal relevance** | Analogies from familiar domains aid understanding | The analogy domain from intake shapes explanations | P1 |

## 3. Learner model

Per learner, per concept:
- `mastery` (0–1) and `band` (§5.6)
- `last_score` (1–4), `attempts`, `last_attempt_at`
- `fsrs_card` (scheduler state from the `fsrs` library), `due`
- `misconceptions[]` (open and resolved)
- `overrides[]` (prerequisite skips, with the warning shown)
- *(P2)* `confidence_calibration`

Per learner, across courses *(P2)*: **shared concept identity.** The same concept appearing in two courses (matched by canonical id, or by semantic similarity with confirmation) shares mastery, so learners skip what they've already proven. Redis vector search is the natural matcher.

## 4. Course lifecycle

`intake → diagnose → assess → map → accept → [teach → assess → grade → adapt]* → complete → review`

### 4.1 Intake (one round)
A single form. Every field is pre-filled with a recommended default so most learners accept in one click:
- topic or goal
- what "expert" means to you
- mode: **cram** (deadline soon: fewer concepts, must-knows first) or **foundation** (full map, spaced review)
- deadline
- target hours and target level
- self-reported current level
- analogy domain
- format preferences (§6)
- *(org)* source documents

### 4.2 Diagnose
Generate **3–4 real questions at the level the learner claimed.** They should be quick concept checks, not self-ratings. Self-reported level is unreliable in both directions; the answers decide.

### 4.3 Assess
Output: assessed level, confidence, evidence (which answers drove it), and gaps. **If evidence and claim disagree, say so plainly with the reason.** No silent re-sequencing and no flattery.

The assessment is **final**: there's no retake. A starting level that turns out too low is corrected by the learning loop instead, because every concept ends in a quiz and a strong result offers a test-out (§4.8, ADR-0006, ADR-0014). Learner answers are evidence, never instructions; asking for a level is not evidence of it.

### 4.4 Map
- **6–20 concepts** (fewer in cram mode). Each has:
  - `id` and `title`
  - a mastery statement ("you can …"), with an objective level
  - `prereqs[]`
  - `est_minutes`
  - `concept_type`: one of algorithm, systems, math, syntax, API, conceptual. This drives the prototype type (§4.5).
  - citations, for grounded courses
- Shown as a dependency-ordered list **with the reasoning for the sequence.**
- Validated in code: no unknown prereqs, no cycles, total time within ±15% of target.
- The learner may cut concepts (P1) or reorder them (P1+). Cutting a prerequisite triggers a warning naming what depends on it. After confirming, each dependent inherits the cut concept's own prerequisites, so ordering still holds (ADR-0017).

### 4.5 Teach (per concept)
1. **Explanation:** brief. Lead with the counterintuitive part, and use the learner's analogy domain.
2. **Worked example:** one complete, realistic example.
3. **Diagram:** Mermaid. Show structure or flow, not decoration.
4. **Prototype** (when format preferences include hands-on). **The bar:** the learner can change something and be surprised. If every input produces the expected result, it's an illustration; go back and find the edge where intuition fails.

   | Concept type | Prototype |
   |---|---|
   | Algorithm | Step-through with a speed control, mutable input, live internal state |
   | Systems / architecture | Simulator with knobs (load, failures, capacity) and a counter showing what breaks first |
   | Math / statistics | Parameters on sliders, plotted, with degenerate cases reachable |
   | Syntax / language | Tiny editor with live output and real error messages |
   | API / library | Runnable calls against a fake in-memory backend |
   | Conceptual | Classification or sorting task scored against the model answer |

   Prototypes are self-contained HTML/JS rendered in a **sandboxed iframe** (scripts allowed, no same-origin). Controls are labeled with real units.
5. **Practice** *(P2)*: faded worked examples, then independent items.

### 4.6 Assess (quiz design rules)
- **4 questions** per concept round.
- **Transfer:** every question uses a situation not used in the lesson. If it can be answered by pattern-matching the lesson's wording, rewrite it.
- **One idea per question,** so a miss tells us which idea failed.
- **Distractors are real misconceptions:** things a half-learner would actually believe, drawn from common confusions, the boundary with prerequisite concepts, and **this learner's logged misconceptions**. Each distractor is tagged with the misconception it represents.
- **At least one question at the mastery statement's objective level.** An "apply" concept needs an "apply" question.
- **No leading phrasing, no giveaways, no hints.**
- Optional fifth item: **explain it in your own words** (self-explanation), graded on the rubric.

### 4.7 Grade
**Rubric (1–4):**

| Score | Meaning |
|---|---|
| 1 | Wrong, or right for the wrong reason |
| 2 | Right eventually, or partially right with visible gaps |
| 3 | Right, clearly, in their own words |
| 4 | Right, **plus** correctly handled the transfer case |

- **Multiple-choice score:** 4/4 correct (including the transfer question) → 4; 3/4 → 3; 2/4 → 2; 0–1 → 1. Only first-try answers count.
- **Short answer:** graded 1–4 by the LLM against a per-question rubric. **A 4 requires transfer; fluent restatement of the lesson caps at 3.**
- **Combined:** when both exist, the concept score is the **lower** of the two. We'd rather under-claim mastery than inflate it, because inflation silently breaks scheduling and unlocking.
- **Feedback names the misconception.** Example: "You said the pod gets evicted. It gets throttled. The underlying belief is that requests and limits do the same thing." Log it.

### 4.8 Adapt (rules first, LLM second)
Deterministic rules decide; the LLM only writes the explanation and remediation content. The plan change below is keyed on the **score**; the resulting band comes from **mastery** (§4.9).

| Score | Outcome | Plan change |
|---|---|---|
| 4 | Concept → mastered (or solid, if earlier attempts were weak; see §4.9) | Offer to **test out** of the next concept: skip its lesson and go straight to its quiz. Mastery still comes only from that graded attempt (ADR-0006) |
| 3 | Concept → solid (first attempt, or after a 2; after a 1 it takes one more attempt, see §4.9) | Continue. Dependents unlock once the band is solid; if it isn't yet, the learner retakes the quiz (no remediation) |
| 1–2 | Concept → shaky/learning | Dependents stay locked. **Insert a remediation concept** that re-teaches from a *different angle* and targets the named misconception |

- **Remediation mechanics** (ADR-0022): the remediation concept is inserted as a new prerequisite of the failed concept, so the gate re-locks the original until the remediation is solid, then the learner retakes it. At most 2 remediations per concept; after that a low score asks for a retake.
- **Prerequisite gate:** a concept unlocks when all its prerequisites are **solid or better**.
- **Override:** a learner may open a locked concept after a specific warning about what will break without the prerequisite. The override is logged. They're adults; they should know the cost.
- **Every plan change creates a new plan version** with a trigger and a plain-English "why" naming the score and the misconception, shown as a diff.

### 4.9 Mastery estimate and bands
Mastery is the product's estimate of current understanding. It's simple and explainable on purpose.
- **Evidence per score:** 1 → 0.20, 2 → 0.50, 3 → 0.80, 4 → 0.95.
- **First graded attempt:** mastery = evidence. One clean attempt is strong evidence.
- **Later attempts:** mastery = 0.3 × previous + 0.7 × evidence. Recent evidence dominates without erasing history: 2 then 3 → 0.71 (solid); 1 then 3 → 0.62 (learning, needs another attempt). Changed from 0.5/0.5, under which a 3 after a 2 stayed "learning" and contradicted §4.8 (ADR-0005).
- **Bands:** shaky < 0.4 ≤ learning < 0.7 ≤ solid < 0.9 ≤ mastered.
- All constants live in config. Tuning them against real outcomes is P2.

### 4.10 Spaced review
- Scheduling uses the open-source **`fsrs`** Python package (Free Spaced Repetition Scheduler, from open-spaced-repetition; verify the current API and license). It replaces a hand-rolled scheduler. Rating map: 1 → Again, 2 → Hard, 3 → Good, 4 → Easy. Every graded attempt is one review, on a day scale: no minute-scale learning steps and no fuzzing (ADR-0018).
- P1 computes and stores due dates; the dashboard shows "N concepts due for review".
- *(P2)* **Review session:** due reviews first (interleaved across concepts, as cheap retrieval warm-up), then one new concept, then one transfer question linking the new concept to an earlier one.
- *(P2)* FSRS parameter optimization from each learner's review history (verify support in `fsrs`).

### 4.11 Close the loop
- *(P1)* After each concept, show what's next and what's due.
- *(P2)* At the end of a session, show what's due and when, and write a session log entry: covered, missed, misconceptions to attack next.

## 5. Grounded (org) courses
- Teach from the provided sources, not general knowledge. **Every factual claim drawn from org docs carries a citation (doc + section).**
- If something isn't in the sources, say **"This isn't covered in your docs"** rather than guessing. Optionally offer general knowledge, clearly labeled as such.
- Quizzes for grounded courses test the org's actual practices (e.g. "per Acme AI's escalation policy, who do you page when…").
- *(P2)* **Source gaps** are surfaced to the org admin as a list (questions learners asked that the docs couldn't answer), turning training into a docs-debt signal.

## 6. Format preferences ("learner type")
Learners choose formats they prefer: reading, quizzes/tests, hands-on building, visual, writing, audio, and more over time.

**Honest note:** research does **not** support "learning styles" in the strong sense, i.e. that matching instruction to a self-identified style improves learning (see the Pashler et al. 2008 review). So Instructor treats these as **format preferences that drive engagement and access**, not as a learning-efficacy claim. Every learner still gets retrieval practice and transfer questions regardless of format. In P1 we implement reading, quizzes, and hands-on; the rest are stored and labeled "coming soon".

## 7. Instructor conduct rules (system-prompt level, all skills)
The instructor:
1. **Asks before explaining** when the learner should be producing the answer.
2. **Never accepts "makes sense" as evidence;** asks the learner to apply the idea instead.
3. **Sequences by prerequisite,** not by what's interesting.
4. **Never flatters.** No "close!", no praise for fluent restatement. Names what was wrong and why.
5. **Never re-sequences silently.** Every plan change shows a diff and a why.
6. **Teaches from provided sources** when there are any, and cites them.
7. **Is honest about tradeoffs** when the learner wants to skip ahead or cram, says the cost once, then respects their choice.

## 8. Course types / playbooks (P2)
Each course type is a skill that adjusts defaults and emphasis:
- **cert-prep:** maps to the exam blueprint, timed practice, heavier review
- **onboarding:** org-grounded, admin-assigned, completion reporting
- **interview-prep:** cram mode, talk-track practice, mock Q&A
- **customer-prep:** grounded in account notes, discovery-question drills
- **new-domain:** foundation mode with broader prerequisites

Orgs can author their own course-type skills *(P3)*.

## 9. Measuring whether it works
Learning effectiveness is measured, not assumed.

| Measure | What it tells us | Phase |
|---|---|---|
| Diagnosis accuracy vs. scripted personas (including an over-claimer) | Does it start learners at the right place? | P1 eval |
| Grader agreement with human labels on 1–4, plus consistency over repeated runs | Can we trust automated grading? | P1 eval |
| Concept-map validity (DAG, time budget) | Are plans structurally sound? | P1 eval |
| Grounding: citations exist, no uncited claims (LLM judge) | Are org courses faithful to sources? | P1 eval |
| Misconception resolution rate | Does remediation actually fix the misunderstanding? | P2 |
| Retention at scheduled review (pass rate of "mastered" concepts) | Is mastery real, or inflated? | P2 |
| Time to solid per concept; time to course completion | Efficiency | P2 |
| Org outcome metrics (e.g. time to on-call-ready, onboarding hours saved) | Business value | P2 |

## 10. Skills that implement this spec
Each is a product skill folder: `backend/agent/skills/<name>/` with `SKILL.md`, `schema.py`, optional `references/`, and `evals/`.

| Skill | Implements | Phase |
|---|---|---|
| `diagnose` | §4.1–4.3 | P1 |
| `map-concepts` | §4.4 | P1 |
| `teach-concept` | §4.5 (+ concept-type prototype guidance in `references/`) | P1 |
| `design-assessment` | §4.6 | P1 |
| `grade` | §4.7 | P1 |
| `remediate` | §4.8 (remediation content and the "why") | P1 |
| `ground-in-sources` | §5 (composed into the other skills for org courses) | P1 |
| `spaced-review` | §4.10–4.11 | P2 |
| `build-prototype` | live prototype generation per §4.5 | P1+ / P2 |
| `coach-chat` | instructor chat: change the plan, explain concepts | P2 |
| `recommend-resources` | vetted external resources with a one-line why, via real web search | P2 |
| course-type playbooks | §8 | P2 |

Deterministic logic (scoring, bands, gating, adaptation rules, FSRS) lives in plain Python (`backend/agent/pedagogy.py`), **not** in skills. Skills do language; code does decisions.

## 11. Explicit non-goals for P1
- Review sessions
- Faded practice
- Interleaving
- Confidence calibration
- Cross-course concept sharing
- Course-type playbooks
- Audio and visual formats
- Live prototype generation

All are designed for (see the data model hooks) but not built.

## 12. Sources (principles, not figures)
- The `deep-learn` Claude skill: inspiration for the core loop (§1, §4)
- Roediger & Karpicke (2006): the testing effect / retrieval practice
- Bjork: desirable difficulties
- Ebbinghaus: the forgetting curve; spacing
- Open Spaced Repetition, FSRS: scheduling algorithm and the `fsrs` package
- Bloom (1984), "The 2 Sigma Problem": mastery learning and one-to-one tutoring
- Anderson & Krathwohl (2001): revised Bloom's taxonomy (objective levels)
- Sweller: cognitive load theory and the worked-example effect
- Rohrer & Taylor: interleaved practice
- Chi et al.: self-explanation
- Pashler, McDaniel, Rohrer & Bjork (2008): the learning-styles critique
