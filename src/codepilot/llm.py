"""Single source of truth for constructing the chat model every agent
(Orchestrator, Coder, Test Agent) uses. Provider-switchable via
`LLM_PROVIDER` (see config.py) so the rest of the codebase never imports
`ChatOpenAI`/`ChatAnthropic` directly - swapping providers is a one-line
change here instead of a find-and-replace across every agent module.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from src.codepilot.config import settings


def build_llm() -> BaseChatModel:
    settings.validate_for_llm()

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.model_name, api_key=settings.openai_api_key)

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.model_name, api_key=settings.anthropic_api_key)

    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r} - expected 'openai' or 'anthropic'."
    )
