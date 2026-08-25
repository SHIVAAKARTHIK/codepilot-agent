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
    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return

    if args.phase1_check:
        phase1_check()
        return

    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
