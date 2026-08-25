# CodePilot — Build Plan

Target: Assignment 01 (Multi-Agent Coding Platform), submitted as public GitHub repo `codepilot-agent`.
Timeline: 2–3 weeks. This plan is phased, not strictly dated — work through phases in order; each phase ends with something runnable and testable before you move on.

---

## 0. Assumptions & defaults (change any of these, just say so)

| Decision | Default | Why |
|---|---|---|
| LLM | Claude Sonnet via `langchain-anthropic` | Best tool-use reliability for this kind of agent work; swap-in for GPT-4o is a 1-line change if needed |
| Agent framework | `deepagents` + LangGraph | Spec'd by the assignment |
| Sandbox | Local temp-dir copy of the target repo subset (not Docker/Daytona) | Simplest to get right on Windows; cloud sandbox stays a bonus |
| GitHub integration | `langchain_community.agent_toolkits.github.GitHubToolkit` (PyGithub under the hood) | Spec'd by the assignment |
| Vector store | ChromaDB, local persistent client | Free, no infra, spec'd |
| TUI | `textual` | Spec'd |
| Guardrails | Custom Python allow/deny checks | NeMo Guardrails is heavyweight for what's actually required — a blocklist function does the same job and is easier to prove correct in a demo |
| Demo target repo | A **second**, small GitHub repo you create and seed with 4–5 deliberate issues (one per skill category) | You cannot demo "issue → PR" convincingly against a large unpredictable OSS repo |
| Target repo language | Small Python (pytest) project | Simplest test-output parsing for the Test Agent |

`codepilot-agent` = the agent's own repo (what you submit).
Call the demo target repo something like `codepilot-demo-target`.

---

## Phase 0 — Setup & scaffolding

- [x] Create public GitHub repo `codepilot-agent` (empty, this repo)
- [x] Create a second public repo `codepilot-demo-target` — a small Python project (e.g. a toy CLI or Flask app, ~10-15 files) that you seed with issues in Phase 9. Doesn't need to be built now, just exist.
- [x] Python project scaffold (structure below), `requirements.txt` / `pyproject.toml`
- [x] `.env.example` with `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO`
- [x] A `main.py` that just boots the orchestrator agent and does one LLM round-trip — sanity check before building anything else

**Done when:** `python main.py --smoke-test` prints a real LLM response. No GitHub, no TUI yet.

---

## Phase 1 — Orchestrator core + state machine

- [x] `create_deep_agent()` orchestrator with a planning-oriented system prompt
- [x] Explicit `TaskState` object: `TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE | FAILED` — a real Python enum/state machine, not just prose in a prompt
- [x] `WorkingMemory` dataclass: issue metadata, repo map, relevant files list, current diff, test results, retry count — passed explicitly to every subagent spawn (not relied on via conversation history, per the spec's context engineering rule)
- [x] Task classification step: LLM call with structured output → one of `bug_fix / feature_addition / dependency_update / documentation / config_change`
- [x] `write_todos` checklist generation per task

**Done when:** given one hardcoded fake issue (no GitHub call), the orchestrator classifies it and produces a todo checklist.

---

## Phase 2 — GitHub polling + issue intake

- [x] ~~`GitHubToolkit` wired to~~ `codepilot-demo-target`: `list_issues` filtered to `ai-assignable` label or unassigned-below-threshold
- [x] Poll loop, configurable interval (default 5 min), plus a `--poll-once` flag for demo/testing so you're not waiting 5 minutes on camera
- [x] In-progress issue tracking (don't double-process an issue already being worked)
- [x] Episodic memory: session task log (issue ID, task type, files modified, outcome, duration) written to LangGraph Memory Store at session end; last-3-session summaries read at startup

> **Deviation:** the installed `langchain-community==0.4.2`'s `GitHubAPIWrapper` (which backs `GitHubToolkit`) only supports GitHub App auth in `validate_environment` — no personal-access-token path exists at all. Registering a GitHub App just to poll one demo repo is disproportionate setup for this project, so [`github_client.py`](src/codepilot/github_client.py) wraps `PyGithub` directly (the same library `GitHubAPIWrapper` itself uses) with plain PAT auth. Required behavior is identical; only the auth mechanism differs. Documented in the README too.

**Done when:** running against `codepilot-demo-target` with one real open issue, the orchestrator picks it up and classifies it.

---

## Phase 3 — Repo Explorer + Repo Map

- [ ] Repo Map builder: walk the repo, produce directory tree + per-file summary (path, language, exported symbols, 1-line description), capped to a 4000-token budget
- [ ] Cache to disk, invalidate via `git diff` against last-seen commit
- [ ] Store the Repo Map in the deepagents virtual filesystem via `write_file` so all subagents share it without rebuilding
- [ ] Retrieval strategy 1 (build first): keyword matching over file summaries, top-K=10
- [ ] Retrieval strategy 2 (build second): embedding search over file-content chunks in ChromaDB — only after keyword matching works end-to-end

**Done when:** given a task description, Repo Explorer returns a ranked file list from the real demo-target repo, and the map is visibly reused (not rebuilt) on a second run with no file changes.

---

## Phase 4 — Coder Agent + sandbox + guardrails (hardest phase — budget the most time here)

- [ ] Local sandbox = fresh temp dir containing only the relevant repo subset (copied, not the live repo)
- [ ] Permission enforcement wrapping the `execute`/`edit_file` tools: reject any operation targeting a path outside the sandbox dir. If the installed `deepagents` version doesn't expose the exact `Permission(...)` primitive from the spec, implement an equivalent guard function yourself and note the substitution in the README — the *behavior* is what's graded, not the exact API shape.
- [ ] Guardrail blocklist on `execute`: reject commands containing `rm -rf`, `curl`, `wget`, `pip install`, or any path outside `/sandbox/`
- [ ] Guardrail blocklist on file edits: reject `.env`, `*.secret`, `*.pem`, `*.key`, `*credentials*`
- [ ] On a blocked operation: raise a `HumanApprovalRequired` event (explain what was attempted) rather than silently failing or silently proceeding
- [ ] Coder inner loop: read relevant files → write plan to todos → `edit_file` surgical edits → `execute` to verify it runs → spawn Test Agent → on failure, retry (max 3)
- [ ] Diff preview: write unified diff to `working/proposed_diff.txt` before finalizing

**Done when:** the Coder can take one real seeded bug-fix issue, make an edit inside the sandbox, and a deliberately-triggered dangerous command (e.g. you have it try `rm -rf` in a test) gets blocked and surfaced, not executed.

---

## Phase 5 — Test Agent + Skills system

- [ ] Test Agent: runs the repo's test suite inside the sandbox, parses pass/fail, reports structured failures back to Coder
- [ ] All 4 skills as structured objects (`name`, `instructions`, `workflow_steps`, `example_prompts`, `forbidden_actions`) — these are cheap (mostly data + prompt text), implement all 4 now rather than deferring:
  - `bug_fix_skill` — reproduce → localize → fix → verify
  - `feature_addition_skill` — explore_pattern → design → implement → test → document
  - `dependency_update_skill` — check_changelog → update → resolve_conflicts → test_all
  - `documentation_skill` — read_existing → draft → review_accuracy → update_index
- [ ] Orchestrator selects skill by classified task type and passes it at subagent spawn time

**Done when:** the same bug-fix issue from Phase 4 runs through the full Coder→Test loop and the failure/retry path is exercised at least once (deliberately break something to force a retry).

---

## Phase 6 — PR Agent + GitHub write path

- [ ] Branch: `codepilot/issue-{issue_number}-{slug}`
- [ ] Structured commit message (summary + bullets + `Closes #N`)
- [ ] PR: title `[CodePilot] {issue title}`, body with summary/approach/files/tests/issue link, labels `codepilot-generated` + `needs-review`, reviewer = issue reporter if available
- [ ] Merge conflict → set `FAILED`, do not attempt auto-resolution
- [ ] HITL approval gates, each as a single reusable "requires approval" check:
  - PR targeting `main`/`master`
  - Any commit touching >5 files
  - Any `execute` call containing `git push`
  - Retry after 2 failed test runs

**Done when:** one seeded issue goes fully issue → branch → commit → PR on `codepilot-demo-target`, and you can trigger at least one of the four HITL gates on camera.

---

## Phase 7 — Semantic memory

- [ ] After a PR opens successfully, extract a "lesson learned" (issue summary, files changed, approach) into ChromaDB keyed by repo + issue type
- [ ] Before starting a new task, retrieve top-3 similar past lessons and inject into the Coder's context

**Done when:** running a second, similar seeded issue visibly retrieves and uses a lesson from the first.

---

## Phase 8 — TUI (build last, once the headless loop works)

Build the TUI only after Phases 1–7 work headlessly via CLI/logs — don't debug agent logic and Textual layout at the same time.

- [ ] 4-panel Textual layout: Issues / Active Task / Agent Logs / Human Approval
- [ ] Issues panel updates live as the poll loop runs
- [ ] Agent Logs streams agent thoughts/tool calls (deepagents streaming)
- [ ] Human Approval panel surfaces HITL interrupts from Phases 4 & 6, takes keyboard input (`approve`/`reject`/`inspect`)
- [ ] `[i]` new free-form task input, `[s]` skip issue, `[q]` quit

**Done when:** you can watch a full issue→PR run live in the TUI, including one approval prompt.

---

## Phase 9 — Demo repo, README, recording

- [ ] Seed `codepilot-demo-target` with 4–5 real issues, one per skill category, small and genuinely fixable (a null check bug, a small feature, a version bump, a missing docstring)
- [ ] README.md: setup instructions, architecture diagram, GIF/recording of the TUI, link to at least one real generated PR
- [ ] Record 5–7 min demo: issue polling → full task execution to PR → a HITL approval prompt → a guardrail block
- [ ] LinkedIn post with the demo video + repo link

---

## Cut list — if you're running short on time, cut in this order

1. Embedding-search retrieval (Phase 3) — keep keyword-only, note it as a limitation
2. Semantic memory (Phase 7) — keep working + episodic only
3. All bonus challenges
4. TUI scope — 2–3 panels working solidly beats 4 half-working panels
5. Skills — last resort only; dropping below 4 costs 15% of the rubric directly, avoid if at all possible

---

## Suggested folder structure

```
codepilot-agent/
  README.md
  BUILD_PLAN.md
  requirements.txt
  .env.example
  src/codepilot/
    orchestrator/
      agent.py
      state_machine.py
      classifier.py
    repo_explorer/
      repo_map.py
      retrieval.py
    coder/
      agent.py
      sandbox.py
      guardrails.py
    test_agent/
      agent.py
    pr_agent/
      agent.py
    skills/
      __init__.py
      bug_fix.py
      feature_addition.py
      dependency_update.py
      documentation.py
    memory/
      episodic.py
      semantic.py
      working.py
    tui/
      app.py
      panels/
    github_client.py
    config.py
  tests/
  demo/
    seed_issues.md
```

---

## Milestone checkpoints

- **End of ~week 1:** headless orchestrator takes one hardcoded issue → classify → explore → code → test → writes a diff file. No GitHub writes yet, no TUI.
- **End of ~week 2:** full GitHub loop works end-to-end (poll → PR opened) against the seeded demo repo for at least 2 of the 4 skill categories. Guardrails demonstrably block a dangerous op. At least one HITL gate demonstrably pauses for approval.
- **End of ~week 2.5–3:** TUI wraps the whole system, README + demo video done, LinkedIn posted.

---

*Next step: Phase 0 scaffolding — say the word and I'll set up the project structure, requirements file, and the two GitHub repos' worth of groundwork.*
