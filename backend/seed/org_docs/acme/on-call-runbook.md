# On-call runbook

For engineers on the primary or secondary rotation for the inference platform. It covers the first hour of a page: what to check, what you may do without asking, and who to tell. For how the services fit together, read the service map first.

## Rotation and handoff

- There is one primary and one secondary. A shift runs Monday 10:00 UTC to the next Monday 10:00 UTC.
- The outgoing primary posts a handoff note in `#oncall-handoff`: open incidents, noisy alerts, and risky deploys still rolling out.
- Before your first shift you need VPN, `kubectl` access to the `inference` namespace, and PagerDuty on your phone. Shadow one full rotation first.

## When you are paged

1. Acknowledge the page within 5 minutes. If the primary has not acknowledged after 10 minutes, PagerDuty pages the secondary.
2. Open the dashboard linked from the alert before you touch anything. You need to know whether things are getting worse.
3. Pick a severity (below). For SEV1 and SEV2, open `#inc-YYYYMMDD-short-name` and post what you see in one sentence.
4. Post an update in that channel every 15 minutes, even if the update is "no change".

## Severity levels

| Level | Meaning | Example | Target |
|---|---|---|---|
| SEV1 | Customers cannot use inference, or data is at risk | Gateway 5xx above 10% for 5 minutes | Acknowledge in 5 min, mitigate in 30 min |
| SEV2 | A large share of requests are degraded | p99 latency above 4 s for 10 minutes | Acknowledge in 15 min, mitigate in 2 h |
| SEV3 | One customer or one non-critical path | A single partner's batch job failing | Next business day |

When unsure between two levels, pick the higher one. You can lower it later.

## Triage by symptom

### 5xx spike at inference-gateway

1. On the gateway dashboard, split the 5xx by status. A 504 means an upstream timed out. A 503 means the gateway itself shed load.
2. Open the `model-router` panels: pool utilization, pool wait (p99) and request rate per pod. Pool wait above 100 ms means requests are queueing for a database connection.
3. Check what shipped in the last two hours (`#deploys`). A regression that started at a deploy is cheaper to roll back than to debug.
4. Check Redis hit rate and Kafka producer errors. Neither is usually the cause, and both are quick to rule out.

### Latency is up but there are no errors

1. Compare p50 and p99. If only p99 moved, suspect queueing (a pool, a thread pool or a rate limiter). If p50 moved too, suspect a slow dependency.
2. Check Postgres replica lag. Routing reads go to replicas, and a lagging replica serves stale routes.
3. Check whether one customer is driving the extra load before scaling anything.

## Mitigations you may use without asking

```bash
# Roll back the last deploy of a service
kubectl -n inference rollout undo deployment/model-router

# Scale out (HPA maximum for model-router is 12 replicas)
kubectl -n inference scale deployment/model-router --replicas=12
```

- Turn on the feature flag `gateway.shed_batch_traffic` to reject batch-priority requests first.
- Pause a single customer's traffic with `gateway.customer_block.<customer-id>`. Tell the account owner right after.
- Do not restart Postgres or Redis. Ask in `#data-platform`.

## Communication

- SEV1: post a status page update within 15 minutes of declaring it, then every 30 minutes until resolved.
- SEV2: post a status page update only if customers have reported it.
- Never promise a time to resolution in a customer-facing message. Say what you know and when you will update next.

## After the incident

- Mark the incident resolved in PagerDuty and in the incident channel.
- Write a blameless postmortem within 5 business days for every SEV1 and SEV2, using the template in `#incident-template`.
- Add one alert or one runbook change for each gap the incident exposed.
