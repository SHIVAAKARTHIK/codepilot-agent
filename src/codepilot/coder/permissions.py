"""Declarative filesystem permission rules - defined here, but **not**
actually usable with the Coder's sandboxed backend. Kept for reference and
to document a real dead end hit while building this.

The spec's `Permission(path=..., access="read_write"|"read_only")` snippet
doesn't exist in the installed `deepagents` version - the real primitive
is `FilesystemPermission(operations=[...], paths=[...],
mode="allow"|"deny"|"interrupt")`, and that part of the earlier
substitution note still holds.

What wasn't caught until testing against a real LLM (Phase 9): passing
`permissions=` to `create_deep_agent()` alongside an execute-capable
backend (`LocalShellBackend`, which implements `SandboxBackendProtocol`)
raises `NotImplementedError` at construction time - `FilesystemMiddleware`
states outright that "Tool-level permissions for the execute tool are not
implemented" for such backends. Every Phase 4-7 test exercised
`run_coder_task(agent=<fake>)`, bypassing `build_coder()`'s real
`create_deep_agent()` call entirely, so this never surfaced until an
actual LLM was run through it.

The forbidden-filename protection this was meant to provide is still
fully in force - it was always also implemented in
`coder/guardrails.py::check_file_edit()`, enforced by
`coder/middleware.py::GuardrailMiddleware` on every `write_file`/
`edit_file` call, independent of this module. `build_coder()`/
`build_test_agent()` no longer pass `permissions=` at all.
"""
from __future__ import annotations

from deepagents import FilesystemPermission

# Both root-level and nested forms, since a `**` glob segment isn't
# guaranteed to match zero directories in every implementation.
_FORBIDDEN_WRITE_GLOBS = [
    "/.env", "/**/.env",
    "/*.secret", "/**/*.secret",
    "/*.pem", "/**/*.pem",
    "/*.key", "/**/*.key",
    "/*credentials*", "/**/*credentials*",
]


def build_coder_permissions() -> list[FilesystemPermission]:
    return [
        FilesystemPermission(operations=["write"], paths=_FORBIDDEN_WRITE_GLOBS, mode="deny"),
    ]
