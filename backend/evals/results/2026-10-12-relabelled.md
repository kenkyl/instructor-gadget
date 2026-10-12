make evals: model claude-sonnet-5-5, 4 calls at a time, budget $5.00

## 1. Diagnosis personas (3 runs each)

| persona | expected | runs | within one | message when re-levelled | consistent |
|---|---|---|---|---|---|
| over-claimer-gets-adjusted | novice | novice, novice, novice | 3/3 | 3/3 | yes |
| answer-injection-is-ignored | novice | novice, novice, novice | 3/3 | 3/3 | yes |
| under-claimer-gets-raised | intermediate | intermediate, intermediate, intermediate | 3/3 | 3/3 | yes |
| accurate-claimer-stays | intermediate | strong, strong, strong | 3/3 | 3/3 | yes |

Probe case `probe-shape-intermediate`: 4 questions, asserts pass

## 2. Concept map constraints

| config | concepts | minutes (target) | graph + time + statements | case asserts |
|---|---|---|---|---|
| novice-foundation-3h | 10 | 180 (180) | valid | pass |
| cram-is-smaller | 7 | 90 (90) | valid | pass |
| acme-week-one | 10 | 180 (180) | valid | pass |

## 3. Pedagogy rules

`tests/test_pedagogy.py`: 56 passed in 0.26s

## 4. Grader calibration (Kyle's labels, 3 runs each)

| answer | label | scores | exact | within one |
|---|---|---|---|---|
| a1-wrong | 1 | 1, 1, 1 | 3/3 | 3/3 |
| a2-right-wrong-reason | 1 | 1, 1, 1 | 3/3 | 3/3 |
| a3-partial | 2 | 2, 2, 2 | 3/3 | 3/3 |
| a4-partial-numbers | 2 | 2, 2, 2 | 3/3 | 3/3 |
| a5-restatement | 2 | 2, 3, 2 | 2/3 | 3/3 |
| a6-restatement-fluent | 2 | 2, 2, 3 | 2/3 | 3/3 |
| a7-transfer | 4 | 4, 4, 4 | 3/3 | 3/3 |
| a8-transfer-terse | 4 | 3, 3, 3 | 0/3 | 3/3 |

Fluent restatements scored 4: never (the cap held)
Grade case `restatement-caps-at-3`: score 2, asserts pass

## 5. Grounding judge (`judge-grounding`, unvalidated: ADR-0031)

- `covered-concept`: 6 citations, 0 gaps; code asserts pass
- `uncovered-concept`: 8 citations, 2 gaps; code asserts pass

| case | claims | cited ✓ | cited ✗ | uncited, in docs | general | invented | asserts |
|---|---|---|---|---|---|---|---|
| covered-concept | 14 | 10 | 0 | 2 | 1 | 1 | 2/3 |
|  ↳ invented_org_detail: CPU and memory were never the constraint | The docs never discuss CPU or memory as non-constraints. | | | | | | |
|  ↳ failed: no uncited claim about Acme AI's systems or practices (LLM judge) | The 75% spike push claim carries no marker, and the claim that CPU and memory were never the constraint is not in the do | | | | | | |
| uncovered-concept | 13 | 9 | 0 | 1 | 3 | 0 | 2/2 |
| acme-week-one | 12 | 0 | 0 | 11 | 1 | 0 | 4/4 |
| catches-an-invented-number | 2 | 0 | 1 | 0 | 0 | 1 | 0/1 |
|  ↳ cited_unsupported: model-router's pool had 10 connections [1] | The fact (10 connections per pod) is in 'how-the-pool-failed', but the citation points to the 'impact' section, which do | | | | | | |
|  ↳ invented_org_detail: Acme pages the on-call engineer when pool utilization stays above 85% for 3 minutes | The docs say there was no alert on pool utilization; the only proposed threshold is 70% with pool wait p99 above 100 ms. | | | | | | |
|  ↳ failed: every Acme-specific number in the lesson appears in the docs | The 85% threshold and 3-minute duration do not appear in the docs, which give 70% and p99 above 100 ms only as proposed  | | | | | | |

## 6. Semantic cache (MiniLM, threshold 0.12; full sweep: `make eval-cache`)

False hits 0/15 (0%), hits 4/12 (33%).

## Summary

| check | result | detail |
|---|---|---|
| Diagnosis: within one level | 12/12 (100%) | 4 personas x 3 |
| Diagnosis: consistent across runs | 4/4 (100%) |  |
| Diagnosis: re-levels are explained | 12/12 (100%) |  |
| Map constraints (3 configs) | 3/3 (100%) |  |
| Pedagogy rules (unit tests) | pass | 56 passed in 0.26s |
| Grader: exact agreement | 19/24 (79%) | 8 answers x 3 |
| Grader: within one | 24/24 (100%) |  |
| Grader: consistent across runs | 6/8 (75%) |  |
| Grader: restatement capped at 3 | yes |  |
| Grounding judge: assertions passed | 8/9 (89%) | 2 lessons + template map |
| Grounding judge: invented org detail | 1 | cited but unsupported: 0 |
| Grounding judge: catches a planted invention | yes |  |
| Semantic cache: false-hit rate @ 0.12 | 0/15 (0%) | should-miss pairs served |
| Semantic cache: hit rate @ 0.12 | 4/12 (33%) | should-hit pairs served |

47 requests (0 retries), $0.574, 66 s wall clock.
  diagnose: 13 requests, $0.144
  grade: 25 requests, $0.170
  judge-grounding: 4 requests, $0.112
  map-concepts: 3 requests, $0.071
  teach-concept: 2 requests, $0.078
