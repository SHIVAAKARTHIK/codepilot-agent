"""CodePilot entrypoint.

Right now this only supports a smoke test to confirm the environment and
LLM connectivity are wired up correctly. Later phases add:
  --poll-once     run a single GitHub issue-polling cycle
  --poll          run the continuous polling loop
  --tui           launch the Textual UI
"""
from __future__ import annotations

import argparse
import sys

from src.codepilot.config import settings


def smoke_test() -> None:
    settings.validate_for_llm()

    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(model=settings.model_name, api_key=settings.anthropic_api_key, max_tokens=64)
    response = llm.invoke("Say exactly: 'CodePilot orchestrator is online.' and nothing else.")
    print(response.content)


def phase1_check() -> None:
    """Phase 1 'done when': one hardcoded fake issue, no GitHub call,
    classified and turned into a todo checklist by the Orchestrator."""
    settings.validate_for_llm()

    from src.codepilot.orchestrator.agent import run_triage
    from src.codepilot.orchestrator.fixtures import FAKE_BUG_ISSUE

    result = run_triage(FAKE_BUG_ISSUE)

    print(f"Issue: #{result.issue.number} {result.issue.title}")
    print(
        f"Classified as: {result.classification.task_type.value} "
        f"(confidence={result.classification.confidence:.2f})"
    )
    print(f"Reasoning: {result.classification.reasoning}")
    print(f"State machine: {result.state_machine.state.value}")
    print(f"State history: {result.state_machine.history}")
    print("\nTodos:")
    for todo in result.todos:
        print(f"  [{todo['status']}] {todo['content']}")
    print(f"\nPlan summary:\n{result.plan_summary}")


def poll_once() -> None:
    """Phase 2 'done when': against the real GitHub repo in .env, the
    poller picks up at least one real open issue and the Orchestrator
    classifies it. Requires ANTHROPIC_API_KEY + GITHUB_TOKEN + GITHUB_REPO."""
    settings.validate_for_llm()
    settings.validate_for_github()

    from src.codepilot.memory.episodic import TaskLogEntry
    from src.codepilot.orchestrator.agent import run_triage
    from src.codepilot.orchestrator.poller import IssuePoller

    poller = IssuePoller()
    issues = poller.poll_once()

    if not issues:
        print(
            "No candidate issues found this cycle (none labelled "
            "'ai-assignable', and no unassigned issue at/under the "
            f"complexity threshold of {poller.complexity_threshold}). "
            "Nothing to triage."
        )
        return

    print(f"Found {len(issues)} candidate issue(s):")
    for issue in issues:
        print(f"  #{issue.number} {issue.title}")

    for issue in issues:
        print(f"\n--- Triaging #{issue.number}: {issue.title} ---")
        result = run_triage(issue)
        print(
            f"Classified as: {result.classification.task_type.value} "
            f"(confidence={result.classification.confidence:.2f})"
        )
        print(f"State: {result.state_machine.state.value}")
        print("Todos:")
        for todo in result.todos:
            print(f"  [{todo['status']}] {todo['content']}")

        poller.episodic.log_task(
            TaskLogEntry(
                issue_id=issue.id,
                task_type=result.classification.task_type.value,
                files_modified=[],
                outcome=result.state_machine.state.value,
                duration_seconds=0.0,
            )
        )
        # Phase 2 stops at triage (Coder/Test/PR agents land in later
        # phases), so this run never actually goes further in-flight.
        poller.in_progress.unmark(issue.id)

    summary = poller.episodic.end_session()
    print(f"\nSession {summary.session_id} logged ({len(summary.tasks)} task(s)) to .codepilot_episodic.json")


def phase3_check(repo_path: str | None = None) -> None:
    """Phase 3 'done when': given a task description, Repo Explorer returns
    a ranked file list, and the map is visibly reused (not rebuilt) on a
    second run with no file changes.

    Demoed against this repo (codepilot-agent) itself by default, since
    codepilot-demo-target is still empty pre-Phase-9 - the builder is fully
    repo-path-agnostic, so nothing here changes once that repo is seeded.
    Pass --repo-path to point it elsewhere.
    """
    from pathlib import Path as _Path

    from src.codepilot.repo_explorer.explorer import RepoExplorer

    target = _Path(repo_path).resolve() if repo_path else settings.project_root
    print(f"Repo: {target}\n")

    explorer = RepoExplorer(target)
    repo_map = explorer.build_or_load()
    print(
        f"First build   -> was_cached={explorer.was_cached}, "
        f"files={len(repo_map.files)}, ~{repo_map.token_estimate()} tokens "
        f"(budget {repo_map.token_budget}, truncated={repo_map.truncated})"
    )

    explorer_again = RepoExplorer(target)
    repo_map_again = explorer_again.build_or_load()
    print(
        f"Second run     -> was_cached={explorer_again.was_cached} "
        f"(should be True: no files changed since the first build)"
    )
    assert repo_map.fingerprint == repo_map_again.fingerprint

    query = "task state machine transitions between orchestrator states"
    results = explorer.select_relevant_files(query, top_k=5)
    print(f"\nQuery: {query!r}")
    print("Top relevant files (keyword strategy):")
    for r in results:
        print(f"  score={r.score:5.1f}  [{r.reason}]  {r.path}")


def phase4_check() -> None:
    """Phase 4 'done when': the Coder takes one real bug-fix issue, makes
    an edit inside its sandbox, and a deliberately-triggered dangerous
    command gets blocked and surfaced, not executed.

    The guardrail-blocking half is proven deterministically by
    tests/test_guardrails.py and tests/test_middleware.py - no LLM
    involved, so it can't hinge on whether a model chooses to attempt
    something risky on a given run. This command proves the other half
    live: a real Coder agent editing real files inside a real sandbox.
    """
    settings.validate_for_llm()

    import tempfile
    from pathlib import Path as _Path

    from src.codepilot.coder.agent import run_coder_task
    from src.codepilot.memory.working import WorkingMemory

    repo_root = _Path(tempfile.mkdtemp(prefix="codepilot_phase4_demo_"))
    (repo_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    working_memory = WorkingMemory(
        issue_id="demo-1",
        issue_title="divide() crashes on division by zero",
        issue_body=(
            "calculator.divide(a, b) raises ZeroDivisionError when b is 0. "
            "It should return None instead of crashing."
        ),
    )
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calculator.py"])

    print(f"Demo repo:  {repo_root}")
    print("Running Coder agent...\n")

    result = run_coder_task(repo_root=repo_root, working_memory=working_memory)

    print(f"Sandbox:    {result.sandbox_dir}")
    print(f"Guardrail violations during this run: {len(result.violations)}")
    print("\nFinal message from Coder:")
    print(result.final_message)
    print("\nDiff (also written to <sandbox>/working/proposed_diff.txt):")
    print(result.diff_text)


def phase5_check() -> None:
    """Phase 5 'done when': the same bug-fix issue from Phase 4 runs
    through the full Coder->Test loop, with a real chance for the
    failure/retry path to fire depending on the Coder's first attempt.

    The retry loop itself is proven deterministically and unconditionally
    by tests/test_coder_retry_loop.py (a fake agent forces a failure then
    a fix - independent of what a real model happens to do on a given
    run). This command is the live companion: a real Coder + real Test
    Agent (spawned via the task tool) against a real bug, with a Skill
    loaded and injected into the Coder's prompt.
    """
    settings.validate_for_llm()

    import tempfile
    from pathlib import Path as _Path

    from src.codepilot.coder.agent import run_coder_task
    from src.codepilot.memory.working import WorkingMemory
    from src.codepilot.skills.registry import load as load_skill

    repo_root = _Path(tempfile.mkdtemp(prefix="codepilot_phase5_demo_"))
    (repo_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    working_memory = WorkingMemory(
        issue_id="demo-2",
        issue_title="divide() crashes on division by zero",
        issue_body=(
            "calculator.divide(a, b) raises ZeroDivisionError when b is 0. "
            "It should return None instead of crashing."
        ),
    )
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calculator.py"])

    print(f"Demo repo:  {repo_root}")
    print("Running Coder + Test Agent loop (spawned via the task tool; "
          "can take a minute or two, longer if a retry fires)...\n")

    result = run_coder_task(
        repo_root=repo_root,
        working_memory=working_memory,
        skill=load_skill("bug_fix"),
    )

    print(f"Sandbox:    {result.sandbox_dir}")
    print(f"Retries:    {result.retries}")
    print(f"Guardrail violations: {len(result.violations)}")
    if result.test_result:
        print(
            f"Final test result: passed={result.test_result.passed} "
            f"no_tests_collected={result.test_result.no_tests_collected} "
            f"counts={result.test_result.counts}"
        )
    print("\nFinal message from Coder:")
    print(result.final_message)
    print("\nDiff (also written to <sandbox>/working/proposed_diff.txt):")
    print(result.diff_text)


class _DryRunGitHubClient:
    """Stands in for GitHubClient in --phase6-check's default (non---live)
    mode: prints what would happen instead of writing to GitHub. Its
    `default_branch` of "main" mirrors a typical fresh repo, so the
    pr_target HITL gate reliably fires - proving that gate live without
    any network call, which is the safest way to demo it on request."""

    def __init__(self) -> None:
        from types import SimpleNamespace

        self.default_branch = "main"
        self.repo = SimpleNamespace(full_name="<dry-run>/<dry-run>")

    def get_default_branch(self) -> str:
        return self.default_branch

    def commit_files_to_branch(self, *, branch: str, files: dict, message: str) -> str:
        print(f"  [dry run] would commit {len(files)} file(s) to branch {branch!r}:")
        print(f"  [dry run] commit message:\n{message}")
        return "dryrun0000000000000000000000000000000000"

    def open_pull_request(self, *, branch, base, title, body, labels, reviewer):
        from types import SimpleNamespace

        print(f"  [dry run] would open PR: {title!r} ({branch} -> {base})")
        print(f"  [dry run] labels: {labels}, reviewer: {reviewer}")
        return SimpleNamespace(html_url="<dry-run: no PR was actually created>", number=0)


def phase6_check(*, live: bool = False, approve_gates: list[str] | None = None) -> None:
    """Phase 6 'done when': one issue goes fully issue -> branch -> commit
    -> PR, and at least one HITL gate is demonstrably triggered.

    Default (no --live): a real Coder + Test Agent run against a
    synthetic bug (same shape as --phase5-check), then the PR Agent's
    real gate-checking logic against a dry-run GitHub stand-in - shows
    exactly which HITL gate(s) fire (almost always pr_target, since a
    fresh repo's default branch is main/master) without writing
    anything to GitHub.

    --live points it at your real GITHUB_REPO and genuinely creates a
    branch/commit/PR there once gates are cleared via --approve-gates -
    only run that once you mean to write to the real repo.
    """
    settings.validate_for_llm()

    import tempfile
    from pathlib import Path as _Path

    from src.codepilot.coder.agent import run_coder_task
    from src.codepilot.memory.working import WorkingMemory
    from src.codepilot.orchestrator.issue import Issue
    from src.codepilot.pr_agent.agent import open_pull_request
    from src.codepilot.skills.registry import load as load_skill

    repo_root = _Path(tempfile.mkdtemp(prefix="codepilot_phase6_demo_"))
    (repo_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    issue = Issue(
        id="demo-3",
        number=999,
        title="divide() crashes on division by zero",
        body="calculator.divide(a, b) raises ZeroDivisionError when b is 0. It should return None instead.",
        reporter=None,
    )

    working_memory = WorkingMemory(issue_id=issue.id, issue_title=issue.title, issue_body=issue.body)
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calculator.py"])

    print(f"Demo repo:  {repo_root}")
    print("Running Coder + Test Agent...\n")
    coder_result = run_coder_task(repo_root=repo_root, working_memory=working_memory, skill=load_skill("bug_fix"))
    print(f"Retries: {coder_result.retries}, changed files: {coder_result.changed_files}")

    if live:
        settings.validate_for_github()
        from src.codepilot.github_client import GitHubClient

        client = GitHubClient()
        print(f"\nLIVE MODE: writing to {settings.github_repo}")
    else:
        client = _DryRunGitHubClient()
        print("\nDRY RUN (no GitHub writes) - pass --live to actually create a branch/commit/PR")

    result = open_pull_request(
        github_client=client,
        issue=issue,
        coder_result=coder_result,
        approach_summary=coder_result.final_message[:500],
        what_changed=[f"Updated {f}" for f in coder_result.changed_files],
        why="Fixes the reported bug.",
        approved_gates=frozenset(approve_gates or []),
    )

    print(f"\nPR Agent result: {result.status}")
    if result.status == "PENDING_APPROVAL":
        for p in result.pending_approvals:
            print(f"  ⚠ gate '{p.gate}' requires approval: {p.reason} ({p.detail})")
        print("\nRe-run with --approve-gates <gate1,gate2,...> to get past these.")
    elif result.status == "PR_OPENED":
        print(f"  {result.pr_url}")
    elif result.status == "FAILED":
        print(f"  {result.error}")


def phase7_check() -> None:
    """Phase 7 'done when': running a second, similar seeded issue visibly
    retrieves and uses a lesson from the first.

    The retrieval-and-injection mechanics are proven deterministically by
    tests/test_coder_semantic_memory.py (a recording fake agent, no LLM
    needed). This command is the live, end-to-end companion: two real
    Coder runs against the same demo repo - a PR opens (dry run) after
    the first, recording a lesson, and the second run's prompt visibly
    includes it.
    """
    settings.validate_for_llm()

    import tempfile
    from pathlib import Path as _Path

    from src.codepilot.coder.agent import run_coder_task
    from src.codepilot.memory.semantic import SemanticMemory
    from src.codepilot.memory.working import WorkingMemory
    from src.codepilot.orchestrator.issue import Issue
    from src.codepilot.pr_agent.agent import open_pull_request
    from src.codepilot.skills.registry import load as load_skill

    repo_root = _Path(tempfile.mkdtemp(prefix="codepilot_phase7_demo_"))
    (repo_root / "calculator.py").write_text(
        "def divide(a, b):\n    return a / b\n\n\ndef modulo(a, b):\n    return a % b\n", encoding="utf-8"
    )

    semantic_memory = SemanticMemory(persist_dir=_Path(tempfile.mkdtemp(prefix="codepilot_phase7_chroma_")))
    repo_id = "codepilot-phase7-demo"

    issue_1 = Issue(
        id="p7-1",
        number=101,
        title="divide() crashes on division by zero",
        body="calculator.divide(a, b) raises ZeroDivisionError when b is 0. It should return None instead.",
        reporter=None,
    )
    wm1 = WorkingMemory(issue_id=issue_1.id, issue_title=issue_1.title, issue_body=issue_1.body)
    wm1.record_classification("bug_fix")
    wm1.record_relevant_files(["calculator.py"])

    print("=== Run 1: fixing divide() ===")
    result_1 = run_coder_task(
        repo_root=repo_root, working_memory=wm1, skill=load_skill("bug_fix"),
        semantic_memory=semantic_memory, repo_id=repo_id,
    )
    print(f"Lessons used (expect 0 - nothing recorded yet): {len(result_1.lessons_used)}")

    pr_result_1 = open_pull_request(
        github_client=_DryRunGitHubClient(),
        issue=issue_1,
        coder_result=result_1,
        approach_summary=result_1.final_message[:500],
        what_changed=[f"Updated {f}" for f in result_1.changed_files],
        why="Fixes the reported bug.",
        approved_gates=frozenset({"pr_target"}),
        semantic_memory=semantic_memory,
        task_type="bug_fix",
    )
    print(f"PR Agent result: {pr_result_1.status} (lesson recorded: {pr_result_1.status == 'PR_OPENED'})")

    issue_2 = Issue(
        id="p7-2",
        number=102,
        title="modulo() crashes on division by zero",
        body=(
            "calculator.modulo(a, b) raises ZeroDivisionError when b is 0, just like divide() "
            "used to. It should return None instead."
        ),
        reporter=None,
    )
    wm2 = WorkingMemory(issue_id=issue_2.id, issue_title=issue_2.title, issue_body=issue_2.body)
    wm2.record_classification("bug_fix")
    wm2.record_relevant_files(["calculator.py"])

    print("\n=== Run 2: fixing modulo() (should reuse the lesson from Run 1) ===")
    result_2 = run_coder_task(
        repo_root=repo_root, working_memory=wm2, skill=load_skill("bug_fix"),
        semantic_memory=semantic_memory, repo_id=repo_id,
    )
    print(f"Lessons used: {len(result_2.lessons_used)}")
    for lesson in result_2.lessons_used:
        print(f"  - {lesson.issue_summary}\n    approach: {lesson.approach}")


def run_tui(*, live: bool = False, repo_path: str | None = None) -> None:
    """Launch the TUI (Phase 8/Component 7).

    Default: demo mode - a synthetic local repo with one seeded bug-fix
    issue, no GitHub credentials needed beyond ANTHROPIC_API_KEY. This is
    the easiest way to watch a full issue -> PR run live, including the
    Human Approval prompt (the demo repo's default branch is treated as
    'main', so the pr_target gate reliably fires - press 'a' to approve
    it and watch the run continue to PR_OPENED).

    --live polls the real GITHUB_REPO for issues. This still needs a
    *local* checkout of that repo for the Coder/Repo Explorer to operate
    on - pass --repo-path pointing at wherever you've `git clone`d
    codepilot-demo-target; there's no auto-clone step (that's Phase 9
    territory, once the demo repo is actually seeded).
    """
    settings.validate_for_llm()

    from src.codepilot.memory.episodic import EpisodicMemory
    from src.codepilot.memory.semantic import SemanticMemory
    from src.codepilot.repo_explorer.explorer import RepoExplorer
    from src.codepilot.tui.app import CodePilotApp

    if live:
        settings.validate_for_github()
        if not repo_path:
            raise SystemExit(
                "--live requires --repo-path pointing at a local checkout of GITHUB_REPO "
                "(clone it yourself first - there's no auto-clone step yet)."
            )
        from pathlib import Path as _Path

        from src.codepilot.github_client import GitHubClient
        from src.codepilot.orchestrator.poller import IssuePoller

        repo_root = _Path(repo_path).resolve()
        github_client = GitHubClient()
        issue_source = IssuePoller(github_client=github_client)
        repo_id = settings.github_repo
    else:
        import tempfile
        from pathlib import Path as _Path

        from src.codepilot.orchestrator.issue import Issue
        from src.codepilot.tui.demo_source import StaticIssueSource

        repo_root = _Path(tempfile.mkdtemp(prefix="codepilot_tui_demo_"))
        (repo_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
        demo_issue = Issue(
            id="tui-demo-1",
            number=1,
            title="divide() crashes on division by zero",
            body="calculator.divide(a, b) raises ZeroDivisionError when b is 0. It should return None instead.",
            reporter=None,
        )
        issue_source = StaticIssueSource([demo_issue])
        github_client = None
        repo_id = "codepilot-tui-demo"

    repo_explorer = RepoExplorer(repo_root)
    episodic_memory = EpisodicMemory()
    semantic_memory = SemanticMemory()

    app = CodePilotApp(
        repo_root=repo_root,
        repo_explorer=repo_explorer,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        github_client=github_client,
        repo_id=repo_id,
        issue_source=issue_source,
        poll_interval_minutes=settings.poll_interval_minutes,
    )
    app.run()
    episodic_memory.end_session()


def main() -> None:
    parser = argparse.ArgumentParser(prog="codepilot")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify config + LLM connectivity with a single round-trip call.",
    )
    parser.add_argument(
        "--phase1-check",
        action="store_true",
        help="Run the Orchestrator against one hardcoded fake issue: classify + write_todos.",
    )
    parser.add_argument(
        "--poll-once",
        action="store_true",
        help="Run one real GitHub polling cycle against GITHUB_REPO and triage any candidate issues.",
    )
    parser.add_argument(
        "--phase3-check",
        action="store_true",
        help="Build/cache the Repo Map for --repo-path (default: this repo) and run a sample retrieval query.",
    )
    parser.add_argument(
        "--repo-path",
        default=None,
        help="Repo to point Repo Explorer at (used with --phase3-check). Defaults to this project.",
    )
    parser.add_argument(
        "--phase4-check",
        action="store_true",
        help="Run the Coder agent against one synthetic bug-fix issue in a sandboxed temp repo.",
    )
    parser.add_argument(
        "--phase5-check",
        action="store_true",
        help="Run the full Coder + Test Agent + retry loop against one synthetic bug-fix issue.",
    )
    parser.add_argument(
        "--phase6-check",
        action="store_true",
        help="Run Coder+Test then the PR Agent's gate-checking (dry run by default; see --live).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="With --phase6-check: actually write to GITHUB_REPO instead of a dry run.",
    )
    parser.add_argument(
        "--approve-gates",
        default="",
        help="With --phase6-check: comma-separated gate names to pre-approve, e.g. pr_target,file_count.",
    )
    parser.add_argument(
        "--phase7-check",
        action="store_true",
        help="Run two similar bug-fix issues; the second should visibly reuse a lesson from the first.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch the TUI (demo mode by default - a synthetic issue, no GitHub needed).",
    )
    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return

    if args.phase1_check:
        phase1_check()
        return

    if args.poll_once:
        poll_once()
        return

    if args.phase3_check:
        phase3_check(args.repo_path)
        return

    if args.phase4_check:
        phase4_check()
        return

    if args.phase5_check:
        phase5_check()
        return

    if args.phase6_check:
        gates = [g.strip() for g in args.approve_gates.split(",") if g.strip()]
        phase6_check(live=args.live, approve_gates=gates)
        return

    if args.phase7_check:
        phase7_check()
        return

    if args.tui:
        run_tui(live=args.live, repo_path=args.repo_path)
        return

    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
