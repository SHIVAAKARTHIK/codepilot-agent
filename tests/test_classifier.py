from src.codepilot.orchestrator.classifier import (
    IssueClassification,
    TaskType,
    classify_issue,
)


class _FakeStructuredRunnable:
    def __init__(self, result: IssueClassification) -> None:
        self._result = result

    def invoke(self, prompt: str) -> IssueClassification:
        self._last_prompt = prompt
        return self._result


class _FakeLLM:
    """Stands in for ChatAnthropic; no network call, no API key needed."""

    def __init__(self, result: IssueClassification) -> None:
        self._result = result
        self.structured: _FakeStructuredRunnable | None = None

    def with_structured_output(self, schema):
        assert schema is IssueClassification
        self.structured = _FakeStructuredRunnable(self._result)
        return self.structured


def test_classify_issue_returns_structured_result():
    expected = IssueClassification(
        task_type=TaskType.BUG_FIX,
        confidence=0.92,
        reasoning="Unhandled exception on empty input.",
    )
    llm = _FakeLLM(expected)

    result = classify_issue(llm, title="Crash on empty list", body="IndexError raised...")

    assert result is expected
    assert result.task_type == TaskType.BUG_FIX
    assert llm.structured is not None
    assert "Crash on empty list" in llm.structured._last_prompt


def test_classify_issue_prompt_includes_body():
    expected = IssueClassification(task_type=TaskType.DOCUMENTATION, confidence=0.8, reasoning="Docs gap.")
    llm = _FakeLLM(expected)

    classify_issue(llm, title="README missing example", body="No usage example for export command")

    assert "No usage example for export command" in llm.structured._last_prompt
