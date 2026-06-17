from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

# 技能加载器，负责从 skills 目录加载技能信息。


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    path: str
    manifest: str


def _read_skill_md(skill_dir: Path) -> Optional[SkillSpec]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    raw = skill_md.read_text(encoding="utf-8")

    # 只解析 front matter
    if not raw.startswith("---"):
        return None

    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None

    front_matter = yaml.safe_load(parts[1]) or {}
    name = front_matter.get("name")
    description = front_matter.get("description")
    if not name or not description:
        return None

    return SkillSpec(
        name=name,
        description=description,
        path=str(skill_dir),
        manifest=raw,
    )


def list_skills() -> List[SkillSpec]:
    specs: List[SkillSpec] = []
    if not SKILLS_DIR.exists():
        return specs

    for d in SKILLS_DIR.iterdir():
        if d.is_dir():
            spec = _read_skill_md(d)
            if spec:
                specs.append(spec)

    return specs


def get_skill(name: str) -> SkillSpec:
    for spec in list_skills():
        if spec.name == name:
            return spec
    raise KeyError(f"unknown skill: {name}")


def build_skill_catalog_text() -> str:
    lines = []
    for spec in list_skills():
        lines.append(f"- name: {spec.name}")
        lines.append(f"  description: {spec.description}")
        lines.append(f"  path: {spec.path}")
    return "\n".join(lines)
