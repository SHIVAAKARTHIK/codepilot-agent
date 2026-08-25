"""Declarative filesystem permission rules for the Coder's sandboxed
backend.

The spec's `Permission(path=..., access="read_write"|"read_only")` snippet
doesn't exist in the installed `deepagents` version (see BUILD_PLAN.md) -
the real primitive is `FilesystemPermission(operations=[...], paths=[...],
mode="allow"|"deny"|"interrupt")`.

General sandbox confinement - the Coder cannot write outside its working
directory - is already provided structurally by
`LocalShellBackend(root_dir=sandbox_dir, virtual_mode=True)`, which blocks
path traversal (`..`, `~`) and verifies every resolved path stays inside
`root_dir`. These rules add the one thing that isn't covered by that:
denying writes to specific forbidden filenames *within* the sandbox.
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
