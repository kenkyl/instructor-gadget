import re
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.registry import SKILLS_DIR, Registry, SkillError


def _copy_skills(tmp_path: Path) -> Path:
    dest = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, dest)
    return dest


def test_diagnose_loads() -> None:
    reg = Registry()
    probe = reg.call("diagnose", "probe")
    assert probe.spec.cache == "never"
    assert probe.output_model.__name__ == "ProbeOutput"
    version = reg.prompt_version("diagnose", "probe")
    print(f"\ndiagnose.probe prompt_version = {version}")
    assert re.fullmatch(r"diagnose@\d+\.\d+\.\d+\+[0-9a-f]{8}", version)


def test_map_concepts_loads() -> None:
    from agent.types import MapInput, MapOutput

    reg = Registry()
    call = reg.call("map-concepts", "map")
    assert call.spec.cache == "never"
    # The kebab-case folder's schema re-exports the importable contract: one class, not two.
    assert (call.input_model, call.output_model) == (MapInput, MapOutput)
    version = reg.prompt_version("map-concepts", "map")
    print(f"\nmap-concepts.map prompt_version = {version}")
    assert re.fullmatch(r"map-concepts@\d+\.\d+\.\d+\+[0-9a-f]{8}", version)


def test_system_prompt_composes_conduct_skill_and_call() -> None:
    prompt = Registry().system_prompt("diagnose", "assess")
    assert prompt.index("Instructor conduct rules") < prompt.index("# Skill: diagnose")
    assert prompt.index("# Skill: diagnose") < prompt.index("# Task: assess")
    assert "adjustment_message" in prompt


def test_editing_a_prompt_changes_prompt_version(tmp_path: Path) -> None:
    skills = _copy_skills(tmp_path)
    before = Registry(skills).prompt_version("diagnose", "probe")
    call_md = skills / "diagnose" / "calls" / "probe.md"
    call_md.write_text(call_md.read_text() + "\n- One more rule.\n")
    after = Registry(skills).prompt_version("diagnose", "probe")
    assert before != after  # cache keys include this, so stale cached outputs can't be served
    assert before.split("+")[0] == after.split("+")[0]  # same semver


def test_missing_call_file_fails_fast(tmp_path: Path) -> None:
    skills = _copy_skills(tmp_path)
    (skills / "diagnose" / "calls" / "assess.md").unlink()
    with pytest.raises(SkillError, match="missing calls/assess.md"):
        Registry(skills)


def test_never_cache_is_enforced(tmp_path: Path) -> None:
    skills = _copy_skills(tmp_path)
    skill_md = skills / "diagnose" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text().replace("probe: { cache: never", "probe: { cache: exact")
    )
    with pytest.raises(SkillError, match="must never be cached"):
        Registry(skills)


def test_assess_requires_adjustment_message_when_levels_differ() -> None:
    output_model = Registry().call("diagnose", "assess").output_model
    base = {
        "claimed_level": "intermediate",
        "assessed_level": "novice",
        "confidence": 0.8,
        "evidence": [{"question_id": "q1", "observation": "restart-first", "points_to": "novice"}],
        "gaps": ["saturation"],
    }
    with pytest.raises(ValidationError, match="adjustment_message is required"):
        output_model.model_validate(base)
    assert output_model.model_validate(base | {"adjustment_message": "You said intermediate…"})


def test_skills_endpoint(client) -> None:
    skills = client.get("/api/skills").json()
    diagnose = next(s for s in skills if s["name"] == "diagnose")
    assert {c["name"] for c in diagnose["calls"]} == {"probe", "assess"}
    assert all(c["cache"] == "never" for c in diagnose["calls"])


def test_teach_concept_loads() -> None:
    from agent.types import LessonOutput, TeachInput

    reg = Registry()
    teach = reg.call("teach-concept", "teach")
    assert teach.spec.cache == "semantic" and teach.spec.stream
    assert (teach.input_model, teach.output_model) == (TeachInput, LessonOutput)
    version = reg.prompt_version("teach-concept", "teach")
    print(f"\nteach-concept.teach prompt_version = {version}")
    assert re.fullmatch(r"teach-concept@\d+\.\d+\.\d+\+[0-9a-f]{8}", version)
