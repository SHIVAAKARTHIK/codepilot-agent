# Seeded issues for `codepilot-demo-target`

The demo target repo is `reportgen` — a tiny numeric-report CLI, built
specifically for this demo. Source: [`../../codepilot-demo-target`](../../codepilot-demo-target)
(sibling directory, not part of this repo). 4 real issues, one per
required Skill category, drafted in
`codepilot-demo-target/.codepilot-issues/*.md` and ready to push +
open via `gh issue create` once GitHub auth is available.

| # | Title | Skill | What "fixed" looks like |
|---|---|---|---|
| 1 | `summarize()` crashes with `ZeroDivisionError` on empty input | `bug_fix_skill` | Failing test added first (none currently covers `summarize([])`), then a guard makes it pass |
| 2 | Add a `--verbose` flag to the CLI | `feature_addition_skill` | New flag prints parsed numbers before the summary; default output unchanged |
| 3 | Bump `requests` to the latest minor version | `dependency_update_skill` | `requirements.txt` updated, changelog checked for breaking changes to `check_status()`, tests still pass |
| 4 | README missing a usage example for `--export` | `documentation_skill` | Example added, matches the existing "Usage" section's style |

## Setup steps (once GitHub auth is available)

```bash
cd codepilot-demo-target
git push -u origin master

gh label create ai-assignable --description "Safe for CodePilot to pick up" --color 0E8A16

for f in .codepilot-issues/*.md; do
  title=$(grep '^TITLE:' "$f" | sed 's/^TITLE: //')
  body=$(sed -n '/^---$/,$p' "$f" | tail -n +2)
  gh issue create --title "$title" --label ai-assignable --body "$body"
done
```

Notes:
- Each issue is scoped to 1–3 files, so the ">5 files changed" HITL gate
  stays a deliberate exception, not the default path.
- Issue #1 is the recommended one to record for the main "issue → PR"
  walkthrough — it's the most visually satisfying (write_todos plan →
  reproduction test → fix → verify).
- The guardrail-block demo (`recording_script.md`'s 5:15–6:00 shot) doesn't
  need its own issue — it's triggered live via `[i]` free-form task input.
