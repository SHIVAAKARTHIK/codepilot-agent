"""Central configuration for CodePilot, loaded from environment variables.

All other modules should import `settings` from here rather than calling
os.environ directly, so every tunable in the assignment spec (poll interval,
token budgets, retry limits, ...) has exactly one place it's defined.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _default_model_for(provider: str) -> str:
    return {"openai": "gpt-4o", "anthropic": "claude-sonnet-5"}.get(provider, "gpt-4o")


@dataclass(frozen=True)
class Settings:
    # --- LLM ---
    # LLM_PROVIDER selects which of the two keys below is used to build
    # every agent's model (Orchestrator, Coder, Test Agent all share one
    # provider - see src/codepilot/llm.py). "openai" is the default since
    # that's what this project is actually being run with.
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "openai").lower())
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    model_name: str = field(
        default_factory=lambda: os.environ.get(
            "CODEPILOT_MODEL", _default_model_for(os.environ.get("LLM_PROVIDER", "openai").lower())
        )
    )

    # --- GitHub ---
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))
    github_repo: str = field(default_factory=lambda: os.environ.get("GITHUB_REPO", ""))

    # --- Orchestrator ---
    poll_interval_minutes: int = field(default_factory=lambda: _int_env("POLL_INTERVAL_MINUTES", 5))
    complexity_threshold: int = field(default_factory=lambda: _int_env("COMPLEXITY_THRESHOLD", 6))

    # --- Repo Explorer ---
    repo_map_token_budget: int = field(default_factory=lambda: _int_env("REPO_MAP_TOKEN_BUDGET", 4000))
    retrieval_top_k: int = field(default_factory=lambda: _int_env("RETRIEVAL_TOP_K", 10))

    # --- Coder ---
    max_coder_retries: int = field(default_factory=lambda: _int_env("MAX_CODER_RETRIES", 3))
    sandbox_root: Path = field(
        default_factory=lambda: _PROJECT_ROOT / os.environ.get("SANDBOX_ROOT", ".codepilot_sandbox")
    )

    # --- Memory ---
    chroma_persist_dir: Path = field(
        default_factory=lambda: _PROJECT_ROOT / os.environ.get("CHROMA_PERSIST_DIR", ".codepilot_chroma")
    )

    project_root: Path = _PROJECT_ROOT

    def validate_for_llm(self) -> None:
        key_name = "OPENAI_API_KEY" if self.llm_provider == "openai" else "ANTHROPIC_API_KEY"
        key_value = self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key
        if not key_value:
            raise RuntimeError(
                f"{key_name} is not set (LLM_PROVIDER={self.llm_provider!r}). "
                "Copy .env.example to .env and fill it in."
            )

    def validate_for_github(self) -> None:
        if not self.github_token or not self.github_repo:
            raise RuntimeError(
                "GITHUB_TOKEN and GITHUB_REPO must be set in .env before talking to GitHub."
            )


settings = Settings()
