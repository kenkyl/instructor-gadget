"""GET /api/skills: what the instructor can do, and exactly which prompt version is live."""

from fastapi import APIRouter
from pydantic import BaseModel

from agent.registry import CachePolicy, get_registry

router = APIRouter(tags=["skills"])


class CallInfo(BaseModel):
    name: str
    cache: CachePolicy
    stream: bool
    prompt_version: str


class SkillInfo(BaseModel):
    name: str
    version: str
    description: str
    modifier: bool
    calls: list[CallInfo]


@router.get("/skills")
async def list_skills() -> list[SkillInfo]:
    reg = get_registry()
    return [
        SkillInfo(
            name=s.meta.name,
            version=s.meta.version,
            description=s.meta.description,
            modifier=s.meta.modifier,
            calls=[
                CallInfo(
                    name=c.name,
                    cache=c.spec.cache,
                    stream=c.spec.stream,
                    prompt_version=reg.prompt_version(s.meta.name, c.name),
                )
                for c in s.calls.values()
            ],
        )
        for s in reg.skills.values()
    ]
