# CodePilot

A multi-agent, terminal-based AI coding platform that polls a GitHub repo for
open issues, plans and implements fixes with a sandboxed Coder agent, verifies
them with a Test agent, and opens pull requests — with human-in-the-loop
approval on risky operations.

Built for the AI Engineering Bootcamp capstone (Assignment 01). See
[BUILD_PLAN.md](BUILD_PLAN.md) for the full phased build plan.

> Status: Phase 0 (scaffolding). Nothing functional beyond an LLM
> connectivity smoke test yet — this section will be replaced with real
> setup/usage/architecture docs as each phase lands.

## Quickstart (current state)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then fill in ANTHROPIC_API_KEY
python main.py --smoke-test
```

## Project layout

```
src/codepilot/
  orchestrator/    # root agent, task state machine, issue classification
  repo_explorer/   # repo map construction + relevant-file retrieval
  coder/           # sandboxed implementation agent + guardrails
  test_agent/      # runs and parses the target repo's test suite
  pr_agent/        # branch/commit/PR creation via GitHub Toolkit
  skills/          # bug_fix / feature_addition / dependency_update / documentation
  memory/          # episodic (session), semantic (ChromaDB), working (task-scoped)
  tui/             # Textual 4-panel interface
```

## License / disclaimer

CodePilot is a fictional product built for learning purposes as part of a
bootcamp capstone.
