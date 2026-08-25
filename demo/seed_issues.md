# Seeded issues for `codepilot-demo-target`

Draft list — one issue per Skill category, small and genuinely fixable, for
Phase 9. Create these as real GitHub issues on the demo target repo once it
exists, labelled `ai-assignable`.

| # | Title | Skill | What "fixed" looks like |
|---|---|---|---|
| 1 | Null pointer / unhandled None when input list is empty | `bug_fix_skill` | Failing test added first, then passes |
| 2 | Add a `--verbose` flag to the CLI | `feature_addition_skill` | New flag works, existing behavior unchanged, documented |
| 3 | Bump `requests` to latest minor version | `dependency_update_skill` | Lockfile updated, full suite still green |
| 4 | `README.md` missing usage example for the `export` command | `documentation_skill` | Example added, matches existing doc style |
| 5 (optional, 5th if time allows) | Config value not validated on startup | `config_change` classification (routes to an existing skill, e.g. bug_fix) | Validation added with a clear error message |

Notes:
- Keep each issue scoped to 1-3 files so the ">5 files changed" HITL gate
  stays a deliberate exception, not the default path.
- Issue #1 doubles as the guardrail-block demo: deliberately ask the Coder
  (via a manual `--task` run) to do something that should be blocked, e.g.
  edit `.env` or run `rm -rf`, and capture that refusal on camera separately
  from the main issue-to-PR flow.
