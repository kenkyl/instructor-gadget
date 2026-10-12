# Service map: the inference platform

How a request travels through the inference platform at Acme AI, what each service owns, and what breaks when a dependency does.

## Overview

Customers call one public API. Behind it, two services of our own and three shared data stores do all the work. Everything runs on Kubernetes in the `inference` namespace.

```
client ─▶ inference-gateway ─▶ model-router ─▶ model backends
                │                   │  │
                │                   │  └─▶ Postgres (routing config, usage)
                ▼                   ├────▶ Redis (response cache)
             Redis (rate limits)    └────▶ Kafka (usage events)
```

## Request path

1. **inference-gateway** authenticates the API key, applies per-customer rate limits and a 10 s overall deadline, then forwards the request.
2. **model-router** looks up the customer's routing rules in Postgres, picks a model backend, and calls it. It checks the response cache in Redis first.
3. After the response, model-router emits a usage event to Kafka for billing and analytics. The customer does not wait for it.

## Services

| Service | What it does | Language | Replicas | Owner |
|---|---|---|---|---|
| `inference-gateway` | Authentication, rate limits, deadlines, load shedding | Go | 8 to 20 (HPA) | Edge team |
| `model-router` | Routing rules, backend selection, response cache, usage events | Python | 6 to 12 (HPA) | Inference team |
| `usage-consumer` | Reads `usage-events` from Kafka and writes billing records | Python | 3 | Billing team |

### inference-gateway

Stateless. Rate-limit counters live in Redis. If Redis is unreachable, the gateway keeps serving and applies a conservative in-memory limit per pod instead of failing requests.

### model-router

Each pod holds a database connection pool of 10 connections to Postgres, with no overflow. A request that cannot get a connection within 1 second fails with a 500 and the error code `pool_timeout`, which the gateway passes through as a 5xx. Six pods therefore use up to 60 of Postgres's 200 connections.

## Data stores

### Postgres

One primary and two read replicas. Routing reads go to replicas and usage writes go to the primary. `max_connections` is 200 and 20 are reserved for administration.

### Redis

A single Redis 8 cluster used for two things: the model-router response cache (TTL 10 minutes) and the gateway's rate-limit counters. It holds no data we cannot lose.

### Kafka

Two topics: `usage-events` (billing and analytics) and `audit-log`. Usage events are produced asynchronously, so a Kafka outage delays billing but does not fail inference requests.

## Failure behaviour

| Dependency down | What customers see | What happens |
|---|---|---|
| Redis | Slower responses | Cache misses go to the backend; the gateway uses in-memory limits |
| Kafka | Nothing | Usage events buffer in memory for up to 5 minutes, then drop and increment `usage_events_dropped` |
| Postgres replica | Nothing | Reads move to the other replica |
| Postgres primary | Errors on new routing changes | Reads keep working from replicas; usage writes retry |
| model-router database pool | 5xx at the gateway | Requests wait for a connection, then fail after 1 second |

## Where to look

- Grafana folder `Inference`: dashboards `gateway-overview`, `model-router-pool` and `postgres-replicas`.
- Logs for every service are in the `inference` index in the log search tool, keyed by `request_id`.
- Deploys are announced in `#deploys`.
