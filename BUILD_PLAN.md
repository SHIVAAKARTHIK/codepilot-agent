# CodePilot — Build Plan

Target: Assignment 01 (Multi-Agent Coding Platform), submitted as public GitHub repo `codepilot-agent`.
Timeline: 2–3 weeks. This plan is phased, not strictly dated — work through phases in order; each phase ends with something runnable and testable before you move on.

---

## 0. Assumptions & defaults (change any of these, just say so)

| Decision | Default | Why |
|---|---|---|
| LLM | ~~Claude Sonnet via `langchain-anthropic`~~ **Switched to OpenAI `gpt-4o` (Phase 9)** via `langchain-openai` — the user has an OpenAI key. Provider is a one-line env var (`LLM_PROVIDER`) thanks to the shared [`src/codepilot/llm.py`](src/codepilot/llm.py) builder every agent goes through; `anthropic` still works if switched back |
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

- [x] Repo Map builder: walk the repo, produce directory tree + per-file summary (path, language, exported symbols, 1-line description), capped to a 4000-token budget
- [x] Cache to disk, invalidate via ~~`git diff`~~ a fingerprint of HEAD + uncommitted changes (generalizes "since last run" to also catch uncommitted edits, not just new commits)
- [x] Store the Repo Map in the deepagents virtual filesystem via `write_file` so all subagents share it without rebuilding
- [x] Retrieval strategy 1 (build first): keyword matching over file summaries, top-K=10
- [x] Retrieval strategy 2 (build second): embedding search over file-content chunks in ChromaDB — only after keyword matching works end-to-end

> **Note:** built deterministically (static analysis via `ast`/regex, no LLM calls) rather than as an LLM-driven agent roaming the filesystem — faster, free, and reproducible; matches how real repo-map tools (e.g. aider) do it. Embedding search uses Chroma's bundled local `all-MiniLM-L6-v2` model (onnxruntime), no external embeddings API/key needed.
>
> **Demoed against `codepilot-agent` itself** (via `main.py --phase3-check --repo-path <path>`), not `codepilot-demo-target`, since that repo is still empty pre-Phase-9. The builder is fully repo-path-agnostic, so nothing changes once it's seeded.

**Done when:** given a task description, Repo Explorer returns a ranked file list from the real demo-target repo, and the map is visibly reused (not rebuilt) on a second run with no file changes.

---

## Phase 4 — Coder Agent + sandbox + guardrails (hardest phase — budget the most time here)

- [x] Local sandbox = fresh temp dir containing only the relevant repo subset (copied, not the live repo)
- [x] Permission enforcement wrapping the `execute`/`edit_file` tools: reject any operation targeting a path outside the sandbox dir. ~~If the installed `deepagents` version doesn't expose the exact `Permission(...)` primitive from the spec~~ — it doesn't; see note below.
- [x] Guardrail blocklist on `execute`: reject commands containing `rm -rf`, `curl`, `wget`, `pip install`, or any path outside `/sandbox/`
- [x] Guardrail blocklist on file edits: reject `.env`, `*.secret`, `*.pem`, `*.key`, `*credentials*`
- [x] On a blocked operation: ~~raise a `HumanApprovalRequired` event~~ return a blocking `ToolMessage` explaining what was attempted, and notify an `on_violation` callback — see note below on why this isn't a full LangGraph `interrupt()` yet.
- [x] Coder inner loop: read relevant files → write plan to todos → `edit_file` surgical edits → `execute` to verify it runs → ~~spawn Test Agent~~ (Test Agent is Phase 5) → on failure, retry (max 3) (retry loop lands with the Test Agent in Phase 5)
- [x] Diff preview: write unified diff to `working/proposed_diff.txt` before finalizing — computed deterministically in code (`difflib`) rather than asking the LLM to hand-author a correct unified diff

> **Key finding, worth reading:** `deepagents`' own `LocalShellBackend` docs are explicit that its `virtual_mode`/`root_dir` path confinement provides **file-operation** sandboxing only — "`virtual_mode=True` and path-based restrictions provide NO security with shell access enabled, since commands can access any path on the system." So the split implemented here is deliberate: `LocalShellBackend(root_dir=sandbox_dir, virtual_mode=True)` genuinely confines `read_file`/`write_file`/`edit_file`/`delete` to the sandbox (blocks `..`/`~`/absolute-path escapes structurally); `FilesystemPermission(mode="deny")` adds the forbidden-filename rule on top of that for file writes; and a custom `GuardrailMiddleware.wrap_tool_call` (see [middleware.py](src/codepilot/coder/middleware.py)) is the actual enforcement layer for `execute`'s command *content* (`rm -rf`, `curl`, `wget`, `pip install`, out-of-sandbox path references), since nothing in deepagents inspects shell command text. This matches deepagents' own stated recommendation for this backend: "Enable Human-in-the-Loop middleware... this is STRONGLY RECOMMENDED as your primary safeguard."
>
> **On the HITL gap:** the blocked-operation path currently returns an explanatory error to the model (proven not to reach the backend — see `tests/test_middleware.py`) rather than a real, resumable LangGraph `interrupt()` requiring a checkpointer. A true pause-for-human-approval needs a persisted graph + the TUI to actually present/resume it, which is Phase 8's job; wiring the checkpointer now would be built before there's any UI to drive it. The `on_violation` callback is the seam Phase 8 hooks into.

**Done when:** the Coder can take one real seeded bug-fix issue, make an edit inside the sandbox, and a deliberately-triggered dangerous command (e.g. you have it try `rm -rf` in a test) gets blocked and surfaced, not executed. Proven two ways: deterministically via `tests/test_guardrails.py` + `tests/test_middleware.py` (doesn't depend on whether a model chooses to attempt something risky), and live via `main.py --phase4-check` (real Coder agent fixing a real bug in a real sandbox).

---

## Phase 5 — Test Agent + Skills system

- [x] Test Agent: runs the repo's test suite inside the sandbox, parses pass/fail, reports structured failures back to Coder
- [x] All 4 skills as structured objects (`name`, `instructions`, `workflow_steps`, `example_prompts`, `forbidden_actions`) — implemented as real `Skill` dataclasses:
  - `bug_fix_skill` — reproduce → localize → fix → verify
  - `feature_addition_skill` — explore_pattern → design → implement → test → document
  - `dependency_update_skill` — check_changelog → update → resolve_conflicts → test_all
  - `documentation_skill` — read_existing → draft → review_accuracy → update_index
- [x] Orchestrator selects skill by classified task type and passes it at subagent spawn time (`skills.load(task_type)` → `skill.to_prompt_block()` injected into the Coder's task prompt)

> **Test Agent design:** split responsibility deliberately, consistent with the "LLM does the creative work, code does the mechanical verification" pattern used since Phase 3. The Test Agent's LLM role is narrow — given what the Coder changed, write/update whatever test(s) are needed (e.g. a bug-fix reproduction test). The actual pass/fail signal the retry loop trusts comes from `run_test_suite()` ([runner.py](src/codepilot/test_agent/runner.py)) — deterministic `pytest` execution + exit-code/output parsing — not the subagent's self-report, since retry-loop correctness shouldn't hinge on a model grading its own work.
>
> **This is the one place in the pipeline using real deepagents subagent spawning**: the Test Agent is built as a genuine `CompiledSubAgent` and attached to the Coder's `subagents=[...]`, so the Coder spawns it through the actual `task` tool, not a Python function call. Orchestrator→Coder and (Phase 6) Coder→PR-Agent stay as explicit Python-orchestrated pipeline stages instead — Coder needs a sandbox path that only exists once Repo Explorer has run for that specific issue, which doesn't fit the static `subagents=[...]` list `create_deep_agent()` wants at Orchestrator-construction time, and a Python-driven retry loop is easier to guarantee correct/testable than leaving max-retries enforcement to the LLM's own re-invocation logic.
>
> **Skills vs. deepagents' native `SkillsMiddleware`:** same divergence pattern as Phases 2/4 — deepagents' own `skills=` mechanism wants directories of `SKILL.md` files, a different shape from the spec's required structured object. `Skill.to_skill_markdown()` / `write_skill_file()` can render one into that format too (kept compatible, not required for the pipeline to work), but the pipeline itself reads the structured object directly.

**Done when:** the same bug-fix issue from Phase 4 runs through the full Coder→Test loop and the failure/retry path is exercised at least once. Proven two ways: deterministically via `tests/test_coder_retry_loop.py` (a fake agent forces a failure then a fix on the 2nd attempt — independent of what a real model happens to do on a given run) and live via `main.py --phase5-check` (real Coder + real Test Agent against a real bug, with a Skill loaded).

---

## Phase 6 — PR Agent + GitHub write path

- [x] Branch: `codepilot/issue-{issue_number}-{slug}`
- [x] Structured commit message (summary + bullets + `Closes #N`)
- [x] PR: title `[CodePilot] {issue title}`, body with summary/approach/files/tests/issue link, labels `codepilot-generated` + `needs-review`, reviewer = issue reporter if available
- [x] Merge conflict → set `FAILED`, do not attempt auto-resolution
- [x] HITL approval gates, each as a single reusable "requires approval" check:
  - PR targeting `main`/`master`
  - Any commit touching >5 files
  - Any `execute` call containing `git push`
  - Retry after 2 failed test runs

> **Implementation notes:**
> - Uses the Git Data API (tree/commit/ref), not the simpler Contents API — lands all changed files in **one** structured commit instead of one commit per file, which is what "a structured commit message" for the whole change actually implies.
> - "Merge conflict" here means the target branch ref can't be fast-forwarded to the new commit (e.g. a second run against the same issue diverged) — the closest real equivalent for an API-based flow with no local working tree to 3-way-merge. Caught as `MergeConflict` → `FAILED`, never auto-resolved.
> - Gate checking happens **before any GitHub write** — `open_pull_request` returns `PENDING_APPROVAL` with zero branch/commit/PR calls made if any gate is un-approved. Same honest gap as Phase 4's guardrails: this refuses rather than silently proceeding, but doesn't yet *pause and resume* a live run — that needs Phase 8's TUI + a checkpointer. `approved_gates` is the seam that phase hooks into.
> - The `git push` gate reuses Phase 4's already-tested `check_execute_command` (Coder/Test Agent `execute` calls), tagged `kind="hitl_gate"` to distinguish it from the hard `"command"` blocks — same refuse-and-surface behavior today, but a real TUI can tell "hard block" apart from "could be approved."

**Done when:** one seeded issue goes fully issue → branch → commit → PR on `codepilot-demo-target`, and you can trigger at least one of the four HITL gates on camera. Proven two ways: deterministically via `tests/test_pr_agent.py` (fake GitHub client, no network — covers all 3 non-execute gates, the merge-conflict path, and reviewer defaulting) and live via `main.py --phase6-check` (real Coder+Test Agent, dry-run PR Agent by default so the `pr_target` gate fires safely on camera without touching GitHub; `--live --approve-gates ...` opts into real writes against `GITHUB_REPO` once you're ready).

---

## Phase 7 — Semantic memory

- [x] After a PR opens successfully, extract a "lesson learned" (issue summary, files changed, approach) into ChromaDB keyed by repo + issue type
- [x] Before starting a new task, retrieve top-3 similar past lessons and inject into the Coder's context

> **Implementation notes:**
> - "Keyed by repository + issue type" is a metadata filter (`where={"$and":[{"repo":...},{"task_type":...}]}`) on one shared Chroma collection, not one physical collection per repo/type pair — idiomatic for this kind of scoped vector search, and avoids fragmenting the index for no benefit.
> - Reuses Chroma's bundled local `all-MiniLM-L6-v2` embedding model — the same one Phase 3's embedding retrieval already uses, no new dependency or external API/key.
> - "After a PR opens successfully" is implemented as "after `open_pull_request` returns `PR_OPENED`" — this codebase has no webhook or polling to observe an actual GitHub *merge* event, so PR-opened is the practical, honestly-documented trigger point rather than true merge confirmation.
> - Injection point: `run_coder_task` retrieves before building its prompt and renders lessons into the same prompt as the Skill block, via `lessons_to_prompt_block()`.

**Done when:** running a second, similar seeded issue visibly retrieves and uses a lesson from the first. Proven two ways: deterministically via `tests/test_coder_semantic_memory.py` (a recording fake agent captures the actual prompt text and confirms the prior lesson's summary/approach appear in it — no LLM needed) and live via `main.py --phase7-check` (two real Coder runs against the same demo repo; the second prints exactly which lesson(s) it received from the first).

---

## Phase 8 — TUI (build last, once the headless loop works)

Build the TUI only after Phases 1–7 work headlessly via CLI/logs — don't debug agent logic and Textual layout at the same time.

- [x] 4-panel Textual layout: Issues / Active Task / Agent Logs / Human Approval
- [x] Issues panel updates live as the poll loop runs
- [x] Agent Logs streams ~~agent thoughts/tool calls (deepagents streaming)~~ pipeline stage progress — see note below
- [x] Human Approval panel surfaces HITL interrupts from Phases 4 & 6, takes keyboard input (`approve`/`reject`/`inspect`)
- [x] `[i]` new free-form task input, `[s]` skip issue, `[q]` quit

> **New in this phase:** [orchestrator/pipeline.py](src/codepilot/orchestrator/pipeline.py) — no single function chained Phases 1–7's pieces together end-to-end until now (issue → triage → explore → code+test → PR, driving the real `TaskStateMachine`). This is what the TUI actually drives per issue.
>
> **Architecture:** two `@work(thread=True)` background workers — a poll loop (producer) and a task processor (consumer of a `deque` queue) — so blocking LLM calls never freeze Textual's asyncio event loop. Cross-thread UI updates go through `call_from_thread`.
>
> **The Human Approval flow is a real pause-and-resume**, not a simulated one: `_handle_approval_needed` blocks the task-processor *worker thread* on a `threading.Event` until the *main UI thread* sets it in response to an actual keypress (`action_approve`/`action_reject`) — the UI stays fully responsive throughout, since only the background worker is waiting. This closes the honest gap flagged in Phases 4 and 6 for the PR Agent's gates (pr_target / file_count / retry_limit), which are pre-flight checks before any GitHub write and so pause/resume cleanly at the pipeline-stage level.
>
> **Scope call on "Agent Logs streams agent thoughts/tool calls (deepagents streaming)":** the panel streams pipeline *stage* progress (TRIAGE → EXPLORE → CODE → TESTING → PR → DONE/FAILED), not live token-by-token deepagents streaming from inside each subagent's `.invoke()` call. Wiring true mid-turn streaming into the same worker-thread architecture — and correctly interleaving it with the approval-pause logic above — was assessed as materially larger scope for a marginal demo improvement, and risked destabilizing the now fully-tested Phases 1–7 this late in the build. Documented here rather than silently narrowed. The Coder/Test Agent's mid-turn tool-call-level guardrail blocks (Phase 4's hard denies, and the `git push` HITL tag) remain refuse-and-surface rather than real LangGraph `interrupt()`-based pause/resume, for the same reason — this is the one part of Phase 8's original ambition intentionally not fully closed.

**Done when:** you can watch a full issue→PR run live in the TUI, including one approval prompt. Proven two ways: deterministically via `tests/test_tui.py` (mounts the real app with Textual's test harness, `run_full_pipeline_for_issue` faked so no LLM is needed; drives the approval flow with a genuine simulated keypress and confirms the background worker thread actually unblocks with the right decision) and live via `main.py --tui` (demo mode: a synthetic seeded issue, no GitHub needed beyond the LLM key — the demo repo's branch reliably trips the `pr_target` gate so you can press `a` and watch the run continue to `PR_OPENED`; `--tui --live --repo-path <path>` polls the real `GITHUB_REPO` against a local checkout).

---

## Phase 9 — Demo repo, README, recording

- [x] Seed `codepilot-demo-target` with 4 real issues, one per skill category (`reportgen`, a tiny CLI: empty-list crash / `--verbose` flag / `requests` version bump / missing README example) — pushed and live: [#1](https://github.com/SHIVAAKARTHIK/codepilot-demo-target/issues/1) [#2](https://github.com/SHIVAAKARTHIK/codepilot-demo-target/issues/2) [#3](https://github.com/SHIVAAKARTHIK/codepilot-demo-target/issues/3) [#4](https://github.com/SHIVAAKARTHIK/codepilot-demo-target/issues/4), labelled `ai-assignable`. Verified live: `--poll-once` discovered all 4 and classified every one into its intended skill category correctly.
- [x] README.md: setup instructions, architecture diagram (Mermaid), deviations summary, known limitations, security decisions — placeholders left for the demo video link and generated-PR link, to fill in once recorded
- [ ] Record 5–7 min demo: issue polling → full task execution to PR → a HITL approval prompt → a guardrail block — **needs a human at the keyboard**; [recording_script.md](demo/recording_script.md) is the shot list. Everything the recording depends on (`--tui --live`, real polling, real Coder/Test Agent runs) is now confirmed working end-to-end against the real demo repo.
- [ ] LinkedIn post with the demo video + repo link — [linkedin_post_draft.md](demo/linkedin_post_draft.md) is a starting draft

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

## Post-Phase-9: bugs found by actually running against OpenAI

Switching the default provider to OpenAI (`gpt-4o`, see the LLM row in
Assumptions & Defaults) and running the live `--phaseN-check` commands for
real surfaced several bugs that every fake-agent-driven unit test had
structurally been unable to catch, since they never exercised the real
`create_deep_agent()` construction or an actual model's behavior. Worth
recording plainly: the deterministic test suite proved the *logic* was
correct, but "141 tests pass" and "the code has never actually been run
end-to-end against a live model" turned out to be two different claims.
Fixed, in the order found:

1. **`write_todos` wasn't a registered tool at all for `gpt-4o`.** Which harness profile `create_deep_agent()` selects — and therefore whether `TodoListMiddleware` gets included — depends on the model provider; it's not guaranteed the way the Phase 1 code assumed. Fix: explicitly pass `middleware=[TodoListMiddleware()]` in `build_orchestrator()` and `build_coder()`.
2. **Without `write_todos` available, gpt-4o substituted `write_file`** to record its plan (writing e.g. `implementation_plan.md`) — and kept retrying that under different filenames for 4 rounds after each permission denial, even while its own final message stated `write_todos` was "typically required." Fix (defense in depth, on top of #1 actually fixing the root cause): the Orchestrator now denies all write access (`FilesystemPermission(mode="deny")` on `/**`), closing off the substitute path structurally.
3. **`build_coder()`/`build_test_agent()` crashed at construction time, always**, the moment they were run with a real LLM: `create_deep_agent(permissions=..., backend=LocalShellBackend(...))` raises `NotImplementedError` because `FilesystemMiddleware` does not support `permissions=` alongside an execute-capable (`SandboxBackendProtocol`) backend. This was in every commit since Phase 4, invisible because every Phase 4-7 test called `run_coder_task(agent=<fake>)`, bypassing the real `build_coder()` entirely. Fix: dropped `permissions=build_coder_permissions()` from both call sites - the forbidden-filename protection it was meant to add was already fully covered by `GuardrailMiddleware`'s `check_file_edit()` on every `write_file`/`edit_file` call, so nothing was actually lost.
4. **`UnicodeEncodeError` printing agent output on Windows** - the default console codepage (`cp1252`) can't encode arbitrary Unicode a model generates. Fix: reconfigure `sys.stdout`/`sys.stderr` to UTF-8 at the top of `main.py`.
5. **`OpenAIRateLimitError` (429) crashed the whole pipeline** on a 30k-tokens-per-minute tier, which a single multi-call agent task (classify → plan → edit → spawn Test Agent → retries) can exhaust on its own. Fix: `max_retries=10` on the provider's own `ChatOpenAI`/`ChatAnthropic` constructor (its SDK-level retry-with-backoff) - not `Runnable.with_retry()`, which returns a wrapper that no longer exposes `.bind_tools()` and silently breaks `create_deep_agent()`.
6. **The diff included garbled `__pycache__/*.pyc` bytecode** once the Coder actually ran code in the sandbox (`python calculator.py` / `pytest` both generate it). `_snapshot()` walked every file with no exclusions beyond the `working/` diff-artifact folder. Fix: exclude `__pycache__`/`.pytest_cache` dirs and `.pyc`/`.pyo` files from the before/after snapshot.

All fixed with accompanying deterministic tests where the bug was
reachable without a real LLM (#3's redundancy, #6's exclusions - 5 new
tests) and confirmed live for the rest (#1, #2, #4, #5) by re-running
`--phase1-check` / `--phase4-check` / `--phase5-check` against the real
account until each produced clean output.

---

*Next step: Phase 0 scaffolding — say the word and I'll set up the project structure, requirements file, and the two GitHub repos' worth of groundwork.*
