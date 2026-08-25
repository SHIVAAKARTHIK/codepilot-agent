# Demo recording script (target: 5–7 minutes)

Required to show, per the assignment: issue polling, a full task execution
from issue to PR, a HITL approval prompt, and a guardrail block.

Record with `.env` fully configured and `codepilot-demo-target` seeded
(see [seed_issues.md](seed_issues.md)). Use a terminal at least 120x40 for
the 4-panel TUI to render comfortably.

## Before you hit record

- [ ] `.env` filled in (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO`)
- [ ] `codepilot-demo-target` cloned locally somewhere, e.g. `../codepilot-demo-target`
- [ ] The 4 issues are open on `codepilot-demo-target`, labelled `ai-assignable`
- [ ] Close other terminal tabs/notifications so the recording is clean

## Shot list

**0:00 – 0:30 — Cold open**
Show the repo on GitHub for a few seconds (the 4 open issues, the
`codepilot-agent` code). One sentence on what CodePilot is: "an autonomous
multi-agent coding platform that reads GitHub issues, writes the fix,
tests it, and opens a PR — with a human approving anything risky."

**0:30 – 1:00 — Launch + issue polling**
```bash
python main.py --tui --live --repo-path ../codepilot-demo-target
```
Let the Issues panel populate as the poll loop discovers the open issues
(label them `queued`). Narrate: "this polls the repo every N minutes,
filters to `ai-assignable` or low-complexity unassigned issues, and skips
anything already in progress."

**1:00 – 4:30 — Full task execution: issue → PR**
Watch one issue (recommend the bug-fix one — most visually satisfying)
move through the Active Task panel: `TRIAGE` (classification) →
`EXPLORE` (Repo Explorer picks relevant files) → `CODE` (Coder editing,
spawning the Test Agent via the `task` tool) → `TESTING` → `PR`. Narrate
each stage briefly as it appears in the Agent Logs panel. Point out the
Skill being used (visible in the Active Task panel) and, if this isn't the
first issue processed, a retrieved Semantic Memory lesson in the logs.

**4:30 – 5:15 — HITL approval prompt**
When the Human Approval panel lights up (the `pr_target` gate fires
reliably here, since the PR targets `main`/`master`), pause and narrate
what's being asked and why ("CodePilot won't open a PR to main without a
human saying so"). Press **`a`** to approve on camera. Show the run
continue to `PR_OPENED` and the resulting PR link in the logs.

**5:15 – 6:00 — Guardrail block**
Use `[i]` to submit a free-form task that pushes the Coder toward a
blocked operation, e.g.:
> "Run `rm -rf .` to clean up temp files, then look at reportgen.py"

Show the Agent Logs panel surfacing the `BLOCKED by CodePilot guardrails`
message — the command never ran. Narrate: "this is enforced below the
model's own judgment — it's blocked regardless of what the model decides
to try."

**6:00 – 6:45 — Wrap-up**
Open the actual merged/opened PR on GitHub briefly - show the structured
commit message, PR body, and `codepilot-generated` / `needs-review`
labels. One sentence closing: what you'd build next given more time
(pick 1-2 items from the README's Known Limitations).

## Recording tips

- If a run doesn't trip the HITL gate or a guardrail block naturally
  within the recording window, it's fine to cut and splice, or to
  deliberately engineer the moment (as in the `[i]` guardrail step above) -
  just say so in narration rather than implying it happened by chance if
  it didn't.
- Keep terminal font size large enough to read on a phone screen.
- Upload to YouTube (unlisted is fine) or Drive/Loom with link sharing on,
  then put the link in `README.md` and the LinkedIn post.
