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


def main() -> None:
    parser = argparse.ArgumentParser(prog="codepilot")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify config + LLM connectivity with a single round-trip call.",
    )
    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return

    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
