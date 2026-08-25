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

    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
