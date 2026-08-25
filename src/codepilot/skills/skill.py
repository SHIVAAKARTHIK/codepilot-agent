"""Skill: a reusable coding workflow the Orchestrator loads by task type
and passes to the Coder subagent at spawn time (Component 4).

Stored as a structured object - `name`, `instructions`, `workflow_steps`,
`example_prompts`, `forbidden_actions` - per spec, not a plain string.

`deepagents` has its own file-based Skills mechanism (`SkillsMiddleware`,
`skills=[<dir>, ...]` pointing at `SKILL.md` files) with a different,
incompatible shape from what the spec requires here. `to_skill_markdown()`
renders a `Skill` into that format too, so one built here is *also*
loadable by deepagents' own SkillsMiddleware if wanted later - not
required for the pipeline (which reads the structured object directly),
just kept compatible rather than ignoring the framework's real mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    instructions: str
    workflow_steps: list[str] = field(default_factory=list)
    example_prompts: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Rendered for injection into the Coder's task prompt at spawn time."""
        lines = [f"## Skill: {self.name}", self.instructions, ""]
        if self.workflow_steps:
            lines.append("Workflow: " + " -> ".join(self.workflow_steps))
        if self.forbidden_actions:
            lines.append("Forbidden for this task type:")
            lines.extend(f"- {a}" for a in self.forbidden_actions)
        return "\n".join(lines)

    def to_skill_markdown(self) -> str:
        """`SKILL.md`-shaped rendering, compatible with deepagents'
        `SkillsMiddleware` (`skills=[<dir containing SKILL.md>]`)."""
        lines = [
            "---",
            f"name: {self.name}",
            f"description: {self.instructions.splitlines()[0][:100]}",
            "---",
            "",
            self.instructions,
            "",
            "## Workflow",
            " -> ".join(self.workflow_steps),
            "",
            "## Example prompts",
            *[f"- {p}" for p in self.example_prompts],
            "",
            "## Forbidden actions",
            *[f"- {a}" for a in self.forbidden_actions],
        ]
        return "\n".join(lines)

    def write_skill_file(self, skills_dir: str | Path) -> Path:
        target_dir = Path(skills_dir) / self.name
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "SKILL.md"
        path.write_text(self.to_skill_markdown(), encoding="utf-8")
        return path
