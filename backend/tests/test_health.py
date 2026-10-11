"""Integration test: needs the data stores running (`make up` locally, service containers in CI)."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_all_ok() -> None:
    with TestClient(app) as client:  # `with` runs the lifespan (opens the connections)
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["redis"] == "ok"
    assert body["query_engine"] == "ok"
    assert body["redis_version"].startswith("8.")
