from dataclasses import dataclass, field

from src.codepilot.github_client import estimate_complexity, is_candidate, to_issue


@dataclass
class _FakeLabel:
    name: str


@dataclass
class _FakeUser:
    login: str


@dataclass
class _FakeGHIssue:
    number: int
    title: str
    body: str
    labels: list[_FakeLabel] = field(default_factory=list)
    assignee: object | None = None
    assignees: list[object] = field(default_factory=list)
    pull_request: object | None = None
    user: _FakeUser | None = None


def test_estimate_complexity_scales_with_body_length():
    assert estimate_complexity("t", "") == 1
    assert estimate_complexity("t", " ".join(["word"] * 40)) == 2
    assert estimate_complexity("t", " ".join(["word"] * 1000)) == 10  # capped


def test_is_candidate_true_for_ai_assignable_label_regardless_of_assignment():
    issue = _FakeGHIssue(
        number=1,
        title="x",
        body=" ".join(["word"] * 500),  # would fail the threshold alone
        labels=[_FakeLabel("ai-assignable")],
        assignee=object(),  # even though assigned
    )
    assert is_candidate(issue, complexity_threshold=1) is True


def test_is_candidate_true_for_unassigned_under_threshold():
    issue = _FakeGHIssue(number=2, title="x", body="short body", labels=[])
    assert is_candidate(issue, complexity_threshold=5) is True


def test_is_candidate_false_when_over_threshold_and_unassigned():
    issue = _FakeGHIssue(number=3, title="x", body=" ".join(["word"] * 500), labels=[])
    assert is_candidate(issue, complexity_threshold=1) is False


def test_is_candidate_false_when_assigned_and_no_label():
    issue = _FakeGHIssue(number=4, title="x", body="short", labels=[], assignee=object())
    assert is_candidate(issue, complexity_threshold=10) is False


def test_to_issue_maps_fields():
    gh_issue = _FakeGHIssue(
        number=7,
        title="Bug: crash",
        body="details",
        labels=[_FakeLabel("ai-assignable"), _FakeLabel("bug")],
        user=_FakeUser("alice"),
    )
    issue = to_issue(gh_issue)
    assert issue.id == "7"
    assert issue.number == 7
    assert issue.title == "Bug: crash"
    assert issue.body == "details"
    assert issue.labels == ["ai-assignable", "bug"]
    assert issue.reporter == "alice"


def test_to_issue_reporter_none_when_no_user():
    gh_issue = _FakeGHIssue(number=8, title="x", body="x", user=None)
    assert to_issue(gh_issue).reporter is None
