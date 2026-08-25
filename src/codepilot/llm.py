"""Single source of truth for constructing the chat model every agent
(Orchestrator, Coder, Test Agent) uses. Provider-switchable via
`LLM_PROVIDER` (see config.py) so the rest of the codebase never imports
`ChatOpenAI`/`ChatAnthropic` directly - swapping providers is a one-line
change here instead of a find-and-replace across every agent module.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from src.codepilot.config import settings


# Every agent's inner loop makes several calls per task (classify, plan,
# edit, spawn Test Agent, retries...), which can trip a tight
# tokens-per-minute rate limit well before the task finishes - observed
# directly on a 30k TPM tier. `max_retries` uses the provider SDK's own
# retry-with-backoff (unlike `Runnable.with_retry()`, which returns a
# wrapper that no longer exposes `.bind_tools()` - breaking
# `create_deep_agent`, since it needs the real `BaseChatModel` interface).
_MAX_RETRIES = 10


def build_llm() -> BaseChatModel:
    settings.validate_for_llm()

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.model_name, api_key=settings.openai_api_key, max_retries=_MAX_RETRIES)

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.model_name, api_key=settings.anthropic_api_key, max_retries=_MAX_RETRIES
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r} - expected 'openai' or 'anthropic'."
    )
