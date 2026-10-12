# Postmortem: model-router connection-pool exhaustion

Blameless postmortem for a SEV1 on 12 March 2026. Inference requests failed with 5xx for 41 minutes after a traffic spike exhausted the database connection pool in `model-router`.

## Summary

At 11:42 UTC a partner's batch job raised request volume to `model-router` by 75%. Every pod ran out of database connections within seconds. Requests waited for a connection, hit the 1-second checkout timeout, and returned 500 `pool_timeout`, which the gateway reported as 5xx. At peak, 22% of inference requests failed. Service recovered at 12:23 UTC after a rollback and a scale-out.

The spike alone would not have caused this. A release two days earlier had doubled how long each request held a connection, which moved the pool from comfortable to a few percent from its limit.

## Impact

- 41 minutes of degraded inference, 22% of requests failing at peak.
- About 310,000 failed requests. Roughly 40 customers retried and saw delayed responses.
- No data was lost. Usage events for failed requests were not emitted, so billing for them is correct.

## Timeline

All times UTC on 12 March 2026.

| Time | Event |
|---|---|
| 11:42 | Partner batch job starts. Request rate per pod rises from about 120 to about 210 per second |
| 11:44 | Pool wait p99 passes 1 s. Failed requests begin |
| 11:47 | Gateway 5xx alert pages the primary |
| 11:55 | Primary suspects Redis and restarts nothing; Redis hit rate is normal |
| 12:04 | Primary finds the pool saturated on the `model-router` dashboard and declares SEV1 |
| 12:11 | Rollback of release `2026.03.10-2` completes. Failures fall but continue |
| 12:17 | model-router scaled from 6 to 12 replicas |
| 12:23 | Error rate back to baseline. Incident resolved |

## Root cause

### How the pool failed

Each `model-router` pod has a pool of 10 database connections and no overflow. A request holds one connection while it reads routing rules. Utilization of the pool is request rate times the time a connection is held, divided by the pool size.

| Condition | Rate per pod | Hold time | Pool | Utilization |
|---|---|---|---|---|
| Before release `2026.03.10-2` | 120 per second | 25 ms | 10 | 30% |
| After the release, normal load | 120 per second | 50 ms | 10 | 60% |
| After the release, during the spike | 210 per second | 50 ms | 10 | 105% |

Above 100% utilization the queue grows without bound: requests arrive faster than connections free up. Below it, queueing stays modest. That is why the service looked healthy at 60% and collapsed within seconds at 105%.

### Why the hold time doubled

Release `2026.03.10-2` added a per-customer quota check inside the same transaction as the routing lookup. The transaction now held its connection through a second query. No test covered pool behaviour, and the change passed review because each query was fast on its own.

## Contributing factors

- There was no alert on pool utilization or pool wait. We found the problem through a downstream symptom, 5xx at the gateway, 20 minutes after it started.
- The first suspect was Redis, because the previous incident involved Redis. The dashboard that showed the pool was not linked from the alert.
- The pool size had not been revisited since the service ran on 3 pods.

## What went well

- The rollback command in the runbook worked as written.
- Shedding batch traffic with `gateway.shed_batch_traffic` protected interactive customers once it was enabled.

## What went badly

- 17 minutes passed between the page and the diagnosis.
- Scaling out was considered only after the rollback did not fully recover service.

## Action items

| Action | Owner | Due |
|---|---|---|
| Alert on pool utilization above 70% and pool wait p99 above 100 ms | Inference team | 19 March |
| Move the quota check out of the routing transaction, restoring about 25 ms hold time | Inference team | 26 March |
| Add a load test that fails a build when utilization exceeds 70% at 1.5x normal rate | Inference team | 9 April |
| Put PgBouncer in front of the primary, instead of raising pool sizes | Data platform | 30 April |
| Link the `model-router-pool` dashboard from the gateway 5xx alert | Edge team | 19 March |

Raising the pool size was considered and rejected for now. Twelve pods with a pool of 20 would open 240 connections against a `max_connections` of 200.
