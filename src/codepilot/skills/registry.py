"""The 4 required Skills (Component 4), registered by task-classification
category so the Orchestrator can select one by task type and pass it to
the Coder at spawn time: `skill = skills.load(task_type)`.
"""
from __future__ import annotations

from src.codepilot.skills.skill import Skill

BUG_FIX_SKILL = Skill(
    name="bug_fix_skill",
    instructions=(
        "Reproduce the bug first (write a failing test that demonstrates it), "
        "then fix it (make that test pass). Do not fix code you cannot first "
        "demonstrate is broken."
    ),
    workflow_steps=["reproduce", "localize", "fix", "verify"],
    example_prompts=[
        "Fix the crash when the input list is empty.",
        "The login endpoint returns 500 instead of 401 for bad credentials.",
    ],
    forbidden_actions=[
        "Fixing a bug without first writing a test that reproduces it",
        "Rewriting unrelated code while fixing a narrow bug",
    ],
)

FEATURE_ADDITION_SKILL = Skill(
    name="feature_addition_skill",
    instructions=(
        "Understand existing patterns before adding new code - read similar "
        "existing features first, then follow their conventions."
    ),
    workflow_steps=["explore_pattern", "design", "implement", "test", "document"],
    example_prompts=[
        "Add a --verbose flag to the CLI.",
        "Add support for exporting reports as CSV.",
    ],
    forbidden_actions=[
        "Breaking backward compatibility of an existing public API",
        "Skipping documentation for a new public-facing feature",
    ],
)

DEPENDENCY_UPDATE_SKILL = Skill(
    name="dependency_update_skill",
    instructions=(
        "Check the changelog between the current and target version for "
        "breaking changes before updating; update lockfiles; run the full "
        "test suite afterward, not just the affected module's tests."
    ),
    workflow_steps=["check_changelog", "update", "resolve_conflicts", "test_all"],
    example_prompts=[
        "Bump requests to the latest minor version.",
        "Update pytest to the latest version and fix any breakage it causes.",
    ],
    forbidden_actions=[
        "Updating past a major-version bump without flagging it for review",
        "Leaving the lockfile out of sync with the manifest",
    ],
)

DOCUMENTATION_SKILL = Skill(
    name="documentation_skill",
    instructions=(
        "Match the existing documentation's style and structure; include "
        "code examples where the existing docs do; update the README if a "
        "public API changed."
    ),
    workflow_steps=["read_existing", "draft", "review_accuracy", "update_index"],
    example_prompts=[
        "README is missing a usage example for the export command.",
        "Document the new --verbose flag.",
    ],
    forbidden_actions=[
        "Documenting behavior that doesn't actually match the code",
        "Introducing a doc style inconsistent with the rest of the repo",
    ],
)

_REGISTRY: dict[str, Skill] = {
    "bug_fix_skill": BUG_FIX_SKILL,
    "bug_fix": BUG_FIX_SKILL,
    "feature_addition_skill": FEATURE_ADDITION_SKILL,
    "feature_addition": FEATURE_ADDITION_SKILL,
    "dependency_update_skill": DEPENDENCY_UPDATE_SKILL,
    "dependency_update": DEPENDENCY_UPDATE_SKILL,
    "documentation_skill": DOCUMENTATION_SKILL,
    "documentation": DOCUMENTATION_SKILL,
    # config_change has no dedicated skill (spec requires exactly 4); a bad
    # config change tends to manifest and get diagnosed like a bug, so it
    # routes to bug_fix_skill's reproduce-first discipline as the closest fit.
    "config_change": BUG_FIX_SKILL,
}


def load(task_type: str) -> Skill:
    try:
        return _REGISTRY[task_type]
    except KeyError as exc:
        raise KeyError(f"No skill registered for task type {task_type!r}") from exc


def all_skills() -> list[Skill]:
    return [BUG_FIX_SKILL, FEATURE_ADDITION_SKILL, DEPENDENCY_UPDATE_SKILL, DOCUMENTATION_SKILL]
