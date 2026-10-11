"""Product skill registry: discovers skill folders, validates them, and composes prompts.

A product skill is a folder `agent/skills/<name>/`:
    SKILL.md          frontmatter (name, version, per-call policy) + skill-level instructions
    calls/<call>.md   instructions for one call
    schema.py         Pydantic Input/Output per call: CALLS = {"<call>": (Input, Output)}
    references/       optional reference material
    evals/            cases for this skill

"Skills do language; code does decisions." The registry only assembles *what to say*; the
LLM client wrapper (agent/llm.py) calls the model, and pedagogy.py makes every decision.
"""

import hashlib
import importlib.util
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

SKILLS_DIR = Path(__file__).parent / "skills"
SHARED_DIR = SKILLS_DIR / "_shared"

CachePolicy = Literal["exact", "semantic", "never"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Learner-specific by definition: caching these would serve one learner's result to another
# (ADR-0007). Enforced here so a frontmatter typo can't silently enable caching.
NEVER_CACHE_SKILLS = frozenset({"diagnose", "grade", "remediate"})

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
SEMVER = r"^\d+\.\d+\.\d+$"


class SkillError(Exception):
    """A skill folder is malformed. Raised at startup so the app fails fast."""


class CallSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache: CachePolicy
    stream: bool = False
    # Thinking tokens count toward max_tokens, so leave headroom above the visible output.
    max_tokens: int = Field(default=8000, gt=0)
    effort: Effort | None = None  # None = the model's default effort


class SkillMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str = Field(pattern=SEMVER)
    description: str
    modifier: bool = False  # composed into other skills (e.g. ground-in-sources); has no calls
    calls: dict[str, CallSpec] = Field(default_factory=dict)


@dataclass(frozen=True)
class Call:
    skill: str
    name: str
    spec: CallSpec
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    instructions: str  # calls/<call>.md
    prompt_hash: str  # sha of every prompt file that shapes this call


@dataclass(frozen=True)
class Skill:
    meta: SkillMeta
    instructions: str  # SKILL.md body
    calls: dict[str, Call]
    path: Path


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()


def _parse_skill_md(path: Path) -> tuple[SkillMeta, str]:
    match = FRONTMATTER.match(path.read_text())
    if not match:
        raise SkillError(f"{path}: missing '---' YAML frontmatter")
    meta = SkillMeta.model_validate(yaml.safe_load(match.group(1)))
    return meta, match.group(2).strip()


def _load_schema(skill_dir: Path) -> ModuleType:
    # Folder names are kebab-case (not always importable), so load schema.py by path. Share one
    # module object with normal imports (`from agent.skills.diagnose.schema import ...`) via
    # sys.modules: two copies would mean two ProbeOutput classes, and isinstance checks fail.
    module_name = f"agent.skills.{skill_dir.name.replace('-', '_')}.schema"
    path = (skill_dir / "schema.py").resolve()
    existing = sys.modules.get(module_name)
    if existing is not None and Path(existing.__file__ or "").resolve() == path:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SkillError(f"{skill_dir}: cannot load schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules.setdefault(module_name, module)  # a copied skill dir (tests) doesn't replace it
    return module


class Registry:
    def __init__(self, skills_dir: Path = SKILLS_DIR) -> None:
        self.skills_dir = skills_dir
        self.conduct = (skills_dir / "_shared" / "conduct.md").read_text().strip()
        # Sent after an output fails validation; `{errors}` is replaced with the error list.
        self.retry_template = (skills_dir / "_shared" / "retry.md").read_text().strip()
        self.skills: dict[str, Skill] = {}
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            skill = self._load(skill_md.parent)
            self.skills[skill.meta.name] = skill

    def _load(self, skill_dir: Path) -> Skill:
        meta, body = _parse_skill_md(skill_dir / "SKILL.md")
        if meta.name != skill_dir.name:
            raise SkillError(f"{skill_dir}: frontmatter name '{meta.name}' != folder name")
        if meta.modifier:
            if meta.calls:
                raise SkillError(f"{meta.name}: modifier skills can't define calls")
            return Skill(meta=meta, instructions=body, calls={}, path=skill_dir)
        if not meta.calls:
            raise SkillError(f"{meta.name}: no calls defined")
        if meta.name in NEVER_CACHE_SKILLS:
            cached = [c for c, s in meta.calls.items() if s.cache != "never"]
            if cached:
                raise SkillError(f"{meta.name}: must never be cached, but {cached} are (ADR-0007)")

        schema_calls: dict[str, tuple[type[BaseModel], type[BaseModel]]] = getattr(
            _load_schema(skill_dir), "CALLS", {}
        )
        if set(schema_calls) != set(meta.calls):
            raise SkillError(
                f"{meta.name}: SKILL.md calls {sorted(meta.calls)} "
                f"!= schema.py CALLS {sorted(schema_calls)}"
            )

        calls: dict[str, Call] = {}
        for call_name, spec in meta.calls.items():
            call_md = skill_dir / "calls" / f"{call_name}.md"
            if not call_md.exists():
                raise SkillError(f"{meta.name}: missing calls/{call_name}.md")
            instructions = call_md.read_text().strip()
            input_model, output_model = schema_calls[call_name]
            calls[call_name] = Call(
                skill=meta.name,
                name=call_name,
                spec=spec,
                input_model=input_model,
                output_model=output_model,
                instructions=instructions,
                prompt_hash=_sha(self.conduct, self.retry_template, body, instructions),
            )
        return Skill(meta=meta, instructions=body, calls=calls, path=skill_dir)

    def call(self, skill: str, call: str) -> Call:
        try:
            return self.skills[skill].calls[call]
        except KeyError:
            raise SkillError(f"unknown call {skill}.{call}") from None

    def prompt_version(self, skill: str, call: str, *, grounded: bool = False) -> str:
        """`name@semver+sha8`: any edit to a prompt file changes it, so caches can't go stale.

        Feeds the LLM cache key and llm_calls.prompt_version.
        """
        c = self.call(skill, call)
        digest = c.prompt_hash
        if grounded:
            digest = _sha(digest, self._grounding().instructions)
        return f"{skill}@{self.skills[skill].meta.version}+{digest[:8]}"

    def system_prompt(self, skill: str, call: str, *, sources: str | None = None) -> str:
        """Shared conduct rules + skill + call (+ grounding rules and docs for org courses)."""
        c = self.call(skill, call)
        parts = [
            "# Instructor conduct rules\n\n" + self.conduct,
            f"# Skill: {skill}\n\n" + self.skills[skill].instructions,
            f"# Task: {call}\n\n" + c.instructions,
        ]
        if sources is not None:
            parts.append("# Grounding rules\n\n" + self._grounding().instructions)
            parts.append("# Source documents\n\n" + sources)
        return "\n\n---\n\n".join(parts)

    def _grounding(self) -> Skill:
        try:
            return self.skills["ground-in-sources"]
        except KeyError:
            raise SkillError("grounding requested but ground-in-sources isn't installed") from None


@lru_cache
def get_registry() -> Registry:
    return Registry()
