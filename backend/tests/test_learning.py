"""J2 lessons through the API: the gate, SSE streaming, storage and reopening."""

import json

import anthropic
import httpx2

from tests.llm_fakes import FakeAnthropic, message
from tests.test_courses import _login, _mapped_course
from tests.test_llm import GOOD_LESSON


def _enrollment(client, fake_llm: FakeAnthropic) -> str:
    course_id = _mapped_course(client, fake_llm)
    return client.post(f"/api/courses/{course_id}/accept").json()["enrollment_id"]


def _events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs, skipping keepalive comments."""
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if "event" in fields:
            out.append((fields["event"], json.loads(fields["data"])))
    return out


def _open(client, enrollment_id: str, concept_id: str):
    return client.post(f"/api/enrollments/{enrollment_id}/concepts/{concept_id}/lesson")


def test_enrollment_lists_the_plan_in_order(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    detail = client.get(f"/api/enrollments/{eid}").json()
    statuses = [(p["concept_id"], p["status"]) for p in detail["progress"]]
    assert statuses[:2] == [("cache-aside", "unlocked"), ("ttls", "locked")]
    assert detail["plan_version"] == 1 and len(statuses) == 6


def test_locked_concept_is_409_before_any_stream(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    assert _open(client, eid, "ttls").status_code == 409
    assert _open(client, eid, "no-such-concept").status_code == 404


def test_lesson_streams_field_deltas_then_is_stored(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    fake_llm.reply(message(GOOD_LESSON))

    res = _open(client, eid, "cache-aside")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    # Without no-transform, Next's gzip held the whole stream back until the end (PC2.2).
    assert "no-transform" in res.headers["cache-control"]
    events = _events(res.text)
    deltas = [d for e, d in events if e == "field_delta"]
    assert len(deltas) > 3  # streamed in pieces, not one blob
    rebuilt: dict[str, str] = {}
    for d in deltas:
        rebuilt[d["field"]] = rebuilt.get(d["field"], "") + d["text"]
    assert rebuilt == GOOD_LESSON
    kind, done = events[-1]
    assert kind == "done" and done["lesson"]["content"]["example_md"] == GOOD_LESSON["example_md"]
    sent = fake_llm.requests[-1]["messages"][0]["content"]
    assert '"assessed_level"' not in sent and "Cache Aside" in sent  # shareable input

    # Stored: reopening returns it without another model call, and progress moved on.
    calls = len(fake_llm.requests)
    stored = client.get(f"/api/enrollments/{eid}/concepts/cache-aside/lesson").json()
    assert stored["content"] == done["lesson"]["content"]
    assert _events(_open(client, eid, "cache-aside").text) == [("done", done)]
    assert len(fake_llm.requests) == calls
    progress = client.get(f"/api/enrollments/{eid}").json()["progress"][0]
    assert progress["status"] == "in_progress"


def test_no_lesson_yet_is_404(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    assert client.get(f"/api/enrollments/{eid}/concepts/cache-aside/lesson").status_code == 404


def test_model_failure_is_an_error_event_and_retryable(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_llm.reply(anthropic.APIConnectionError(request=request))

    events = _events(_open(client, eid, "cache-aside").text)

    assert [e for e, _ in events] == ["error"]
    fake_llm.reply(message(GOOD_LESSON))
    assert _events(_open(client, eid, "cache-aside").text)[-1][0] == "done"


def test_other_users_cannot_open_lessons(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    _login(client, "priya")
    assert client.get(f"/api/enrollments/{eid}").status_code == 404
    assert _open(client, eid, "cache-aside").status_code == 404
