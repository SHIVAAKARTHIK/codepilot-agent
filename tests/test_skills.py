import pytest

from src.codepilot.skills.registry import all_skills, load
from src.codepilot.skills.skill import Skill


def test_all_four_skills_registered():
    names = {s.name for s in all_skills()}
    assert names == {
        "bug_fix_skill",
        "feature_addition_skill",
        "dependency_update_skill",
        "documentation_skill",
    }


@pytest.mark.parametrize(
    "task_type,expected_skill_name",
    [
        ("bug_fix", "bug_fix_skill"),
        ("bug_fix_skill", "bug_fix_skill"),
        ("feature_addition", "feature_addition_skill"),
        ("dependency_update", "dependency_update_skill"),
        ("documentation", "documentation_skill"),
        ("config_change", "bug_fix_skill"),  # documented fallback
    ],
)
def test_load_resolves_task_type_to_skill(task_type, expected_skill_name):
    assert load(task_type).name == expected_skill_name


def test_load_unknown_task_type_raises():
    with pytest.raises(KeyError):
        load("not_a_real_task_type")


def test_skill_has_all_required_structured_fields():
    for skill in all_skills():
        assert skill.name
        assert skill.instructions
        assert len(skill.workflow_steps) >= 3
        assert len(skill.example_prompts) >= 1
        assert len(skill.forbidden_actions) >= 1


def test_to_prompt_block_includes_workflow_and_forbidden_actions():
    skill = load("bug_fix_skill")
    block = skill.to_prompt_block()
    assert skill.name in block
    assert "reproduce -> localize -> fix -> verify" in block
    for action in skill.forbidden_actions:
        assert action in block


def test_to_skill_markdown_has_frontmatter():
    skill = Skill(
        name="demo_skill",
        instructions="Do the thing carefully.",
        workflow_steps=["a", "b"],
        example_prompts=["do it"],
        forbidden_actions=["don't do the bad thing"],
    )
    md = skill.to_skill_markdown()
    assert md.startswith("---\nname: demo_skill\n")
    assert "description:" in md
    assert "a -> b" in md


def test_write_skill_file_creates_skill_md(tmp_path):
    skill = load("documentation_skill")
    path = skill.write_skill_file(tmp_path)

    assert path.name == "SKILL.md"
    assert path.exists()
    assert path.parent.name == "documentation_skill"
    assert "documentation_skill" in path.read_text(encoding="utf-8")
