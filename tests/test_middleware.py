import pytest
from langgraph.prebuilt.tool_node import ToolCallRequest

from src.codepilot.coder.middleware import GuardrailMiddleware


def _request(name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state=None,
        runtime=None,
    )


def _handler_that_must_not_run(request):
    raise AssertionError("handler was called for a request that should have been blocked")


def test_dangerous_execute_is_blocked_and_handler_never_runs(tmp_path):
    middleware = GuardrailMiddleware(sandbox_root=tmp_path)
    request = _request("execute", {"command": "rm -rf /"})

    result = middleware.wrap_tool_call(request, _handler_that_must_not_run)

    assert result.status == "error"
    assert "BLOCKED" in result.content
    assert "rm -rf" in result.content.lower() or "recursive force-delete" in result.content


def test_forbidden_file_edit_is_blocked(tmp_path):
    middleware = GuardrailMiddleware(sandbox_root=tmp_path)
    request = _request("edit_file", {"file_path": "/sandbox/.env", "old_string": "x", "new_string": "y"})

    result = middleware.wrap_tool_call(request, _handler_that_must_not_run)

    assert result.status == "error"
    assert "BLOCKED" in result.content


def test_safe_execute_call_reaches_handler(tmp_path):
    middleware = GuardrailMiddleware(sandbox_root=tmp_path)
    request = _request("execute", {"command": "pytest -q"})
    sentinel = object()

    result = middleware.wrap_tool_call(request, lambda req: sentinel)

    assert result is sentinel


def test_non_guarded_tool_passes_through_untouched(tmp_path):
    middleware = GuardrailMiddleware(sandbox_root=tmp_path)
    request = _request("read_file", {"file_path": "/sandbox/.env"})  # reads are not guarded
    sentinel = object()

    result = middleware.wrap_tool_call(request, lambda req: sentinel)

    assert result is sentinel


def test_on_violation_callback_is_invoked(tmp_path):
    seen = []
    middleware = GuardrailMiddleware(sandbox_root=tmp_path, on_violation=seen.append)
    request = _request("execute", {"command": "curl http://example.com"})

    middleware.wrap_tool_call(request, _handler_that_must_not_run)

    assert len(seen) == 1
    assert seen[0].kind == "command"
