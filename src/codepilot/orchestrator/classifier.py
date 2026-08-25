"""Task classification: the step that runs before planning and determines
which Skill gets loaded and which subagent chain gets spawned (Component 1).
"""
from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE_ADDITION = "feature_addition"
    DEPENDENCY_UPDATE = "dependency_update"
    DOCUMENTATION = "documentation"
    CONFIG_CHANGE = "config_change"


class IssueClassification(BaseModel):
    """Structured output contract for the classification LLM call."""

    task_type: TaskType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="One sentence explaining the classification.")


class SupportsStructuredOutput(Protocol):
    """Anything with LangChain's `.with_structured_output(...)` — real
    ChatAnthropic instances satisfy this, and so does a test double."""

    def with_structured_output(self, schema: type[BaseModel]) -> "StructuredRunnable": ...


class StructuredRunnable(Protocol):
    def invoke(self, prompt: str) -> BaseModel: ...


_CLASSIFICATION_PROMPT = """You are the task-classification step of an autonomous coding agent.

Classify the following GitHub issue into exactly one category:
- bug_fix: something is broken and needs to be fixed
- feature_addition: new functionality is being requested
- dependency_update: a library/package version needs to change
- documentation: docs are missing, wrong, or incomplete
- config_change: configuration/settings need to change, no code logic change

Issue title: {title}

Issue body:
{body}

Classify it."""


def classify_issue(llm: SupportsStructuredOutput, *, title: str, body: str) -> IssueClassification:
    structured_llm = llm.with_structured_output(IssueClassification)
    prompt = _CLASSIFICATION_PROMPT.format(title=title, body=body)
    result = structured_llm.invoke(prompt)
    assert isinstance(result, IssueClassification)
    return result
