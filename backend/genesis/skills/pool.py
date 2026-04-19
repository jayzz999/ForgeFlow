"""Genesis-internal skill pool. Read/write hybrid YAML+markdown files.

Files live at $GENESIS_STORAGE/_skill_pool/sk_<id>.md.
Frontmatter is structured (machine-parseable for inheritance/lineage).
Body is LLM-written narrative guidance (read by future organisms).
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import yaml  # PyYAML ships with chromadb; if missing, pip install pyyaml

from .. import store


def _pool_dir() -> Path:
    d = Path(store._BASE) / "_skill_pool"  # noqa: SLF001
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Skill:
    skill_id: str
    name: str
    description: str
    distilled_at: datetime
    parent_organisms: list[str]
    parent_skills: list[str]
    generation: int
    fitness_at_death: float
    n_decisions_distilled: int
    trigger_patterns: list[str]
    forbidden_patterns: list[str]
    body: str


def new_skill_id() -> str:
    return f"sk_{uuid4().hex[:10]}"


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _serialize(skill: Skill) -> str:
    fm = {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "distilled_at": skill.distilled_at.isoformat(),
        "parent_organisms": list(skill.parent_organisms),
        "parent_skills": list(skill.parent_skills),
        "generation": skill.generation,
        "fitness_at_death": skill.fitness_at_death,
        "n_decisions_distilled": skill.n_decisions_distilled,
        "trigger_patterns": list(skill.trigger_patterns),
        "forbidden_patterns": list(skill.forbidden_patterns),
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + skill.body


def _deserialize(text: str) -> Skill:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("malformed skill file: missing frontmatter")
    fm = yaml.safe_load(m.group(1))
    body = m.group(2)
    return Skill(
        skill_id=fm["skill_id"],
        name=fm["name"],
        description=fm["description"],
        distilled_at=datetime.fromisoformat(fm["distilled_at"]),
        parent_organisms=list(fm.get("parent_organisms", [])),
        parent_skills=list(fm.get("parent_skills", [])),
        generation=int(fm.get("generation", 1)),
        fitness_at_death=float(fm.get("fitness_at_death", 0.0)),
        n_decisions_distilled=int(fm.get("n_decisions_distilled", 0)),
        trigger_patterns=list(fm.get("trigger_patterns", [])),
        forbidden_patterns=list(fm.get("forbidden_patterns", [])),
        body=body,
    )


def write(skill: Skill) -> Path:
    """Atomic write — temp file + rename. Survives crashes mid-write."""
    target = _pool_dir() / f"{skill.skill_id}.md"
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=skill.skill_id + ".", suffix=".tmp",
                                         dir=str(_pool_dir()))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(_serialize(skill))
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise
    return target


def load(skill_id: str) -> Optional[Skill]:
    p = _pool_dir() / f"{skill_id}.md"
    if not p.exists():
        return None
    return _deserialize(p.read_text(encoding="utf-8"))


def list_summaries() -> list[dict]:
    """List all pool skills as frontmatter dicts (no body, fast)."""
    out = []
    for p in sorted(_pool_dir().glob("sk_*.md")):
        text = p.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1))
        out.append(fm)
    return out


def delete(skill_id: str) -> bool:
    p = _pool_dir() / f"{skill_id}.md"
    if p.exists():
        p.unlink()
        return True
    return False
