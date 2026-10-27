"""Skills: reusable procedures stored as `<dir>/<skill>/SKILL.md` with a YAML
frontmatter (`name`, `description`). Searched, highest precedence first, in
`<workspace>/skills/`, `~/.tpagent/skills/` and the skills shipped with the
package (`<repo>/skills/`). The system prompt lists name + description; the
model calls `use_skill(name)` to load the full body."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .base import Tool
from .workspace import get_workspace

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "skills"
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    path: Path

    def body(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        return _FRONTMATTER.sub("", text, count=1).strip()


def skill_dirs() -> list[Path]:
    return [get_workspace() / "skills", Path.home() / ".tpagent" / "skills", BUNDLED_DIR]


def parse_skill(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta: dict[str, str] = {}
    m = _FRONTMATTER.match(text)
    if m:
        for line in m.group(1).splitlines():
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip().lower()] = value.strip().strip("'\"")
    name = meta.get("name") or path.parent.name
    return Skill(name=name, description=meta.get("description", ""), path=path)


def load_skills() -> list[Skill]:
    """All skills, de-duplicated by name (first directory wins)."""
    seen: dict[str, Skill] = {}
    for d in skill_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*/SKILL.md")):
            skill = parse_skill(f)
            if skill and skill.name not in seen:
                seen[skill.name] = skill
    return list(seen.values())


def skills_summary() -> str:
    """One line per skill for the system prompt ('' when none)."""
    return "\n".join(f"- {s.name}: {s.description}" for s in load_skills())


def use_skill(name: str) -> str:
    skills = {s.name: s for s in load_skills()}
    skill = skills.get(name.strip())
    if skill is None:
        return f"Error: unknown skill '{name}'. Available: {', '.join(sorted(skills)) or '(none)'}"
    return f"# Skill: {skill.name}\n(source: {skill.path})\n\n{skill.body()}"


TOOLS: list[Tool] = [
    Tool(
        "use_skill",
        "Load the full instructions of a skill listed in the system prompt. Call it before starting a task the skill covers, then follow it.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        use_skill, tags=["skills", "read"],
    ),
]

__all__ = ["TOOLS", "Skill", "load_skills", "skills_summary", "use_skill", "parse_skill", "skill_dirs"]
