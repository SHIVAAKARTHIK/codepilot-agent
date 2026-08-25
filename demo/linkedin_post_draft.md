# LinkedIn post draft

Edit freely — this is a starting point, not a script to read verbatim.
Replace `[DEMO VIDEO LINK]` before posting.

---

I just shipped **CodePilot** — a multi-agent AI coding platform built for
my AI Engineering Bootcamp capstone.

It watches a GitHub repo for open issues, and for each one: classifies the
task, builds a compressed map of the repo to figure out which files
matter, implements a fix inside a sandboxed environment, spawns a
dedicated agent to add test coverage, verifies everything actually passes,
and opens a structured pull request — pausing for a human's approval
before anything risky (a PR to main, a large diff, too many failed
retries) goes through.

A few things I focused on that I think matter more than the demo itself:

🔒 **Guardrails that don't rely on the model being well-behaved.** The
Coder's sandbox blocks dangerous shell commands and secret-file edits at
the tool-call layer — not by asking nicely in the prompt.

🧠 **Three tiers of memory.** Working memory scoped to one task, episodic
memory that remembers what happened last session, and semantic memory
(vector search over past "lessons learned") that gets injected into future
similar tasks — I watched it visibly reuse a fix approach from an earlier
issue on a related bug.

🧪 **Two kinds of proof for every feature**, not one: a deterministic test
suite (141 tests) that proves the logic works independent of what any
particular LLM run does, and a live end-to-end demo against a real repo.

Full write-up, architecture diagram, and the complete build log (including
every place the real library APIs diverged from the spec, and why) is in
the repo.

Demo video: [DEMO VIDEO LINK]
Code: https://github.com/SHIVAAKARTHIK/codepilot-agent

#AIEngineering #MultiAgentSystems #LangGraph #BuildInPublic
