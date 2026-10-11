"""Which seeded prototype (if any) a lesson shows (spec §4.5; live generation is P1+).

Only for learners who chose hands-on, and only when the concept is about what the prototype
simulates. Matching is a deterministic rule on the concept's own words, so a lesson never
shows a simulator for something else.
"""

import re
import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.types import Concept
from app.models import Prototype

HANDS_ON = "hands_on"

# slug → what a concept must mention to get it. Slugs are seeded by `make seed`.
MATCHES: dict[str, re.Pattern[str]] = {
    "conn-pool-sim": re.compile(
        r"connection pool|pool (exhaustion|size|sizing|saturation|starvation)|pool exhaust",
        re.IGNORECASE,
    ),
}


class PrototypeView(BaseModel):
    slug: str
    title: str
    html: str  # render ONLY in <iframe sandbox="allow-scripts" srcdoc=…> (CLAUDE.md)


def matching_slug(concept: Concept) -> str | None:
    text = " ".join([concept.id.replace("-", " "), concept.title, concept.mastery_statement])
    return next((slug for slug, rx in MATCHES.items() if rx.search(text)), None)


async def prototype_for(db: AsyncSession, concept: Concept, formats: list[str]) -> uuid.UUID | None:
    if HANDS_ON not in formats:
        return None
    slug = matching_slug(concept)
    if slug is None:
        return None
    return await db.scalar(select(Prototype.id).where(Prototype.slug == slug))


async def prototype_view(db: AsyncSession, prototype_id: uuid.UUID | None) -> PrototypeView | None:
    if prototype_id is None:
        return None
    proto = await db.get(Prototype, prototype_id)
    if proto is None:
        return None
    return PrototypeView(slug=proto.slug, title=proto.title, html=proto.html)
