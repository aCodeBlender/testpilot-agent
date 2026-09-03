"""LLM configuration — separate from AppConfig.

Environment variables (all required when --goal is used):
    TESTPILOT_LLM_API_KEY   — API key for the LLM provider
    TESTPILOT_LLM_BASE_URL  — OpenAI-compatible base URL
    TESTPILOT_LLM_MODEL     — Model name
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, SecretStr

from testpilot.llm.exceptions import LLMConfigError


class LLMConfig(BaseModel):
    """Configuration for an OpenAI-compatible LLM provider.

    ``api_key`` uses ``SecretStr`` so the raw value never appears in
    ``repr()``, ``str()``, or serialized output.
    """

    api_key: SecretStr
    base_url: str
    model: str
    timeout_seconds: float = Field(default=30.0, ge=1.0)


def load_llm_config_from_env() -> LLMConfig:
    """Load LLM configuration from environment variables.

    All three variables are required.  No hard-coded provider defaults.

    Raises
    ------
    LLMConfigError
        If any required variable is missing.
    """
    missing: list[str] = []
    api_key = os.environ.get("TESTPILOT_LLM_API_KEY")
    base_url = os.environ.get("TESTPILOT_LLM_BASE_URL")
    model = os.environ.get("TESTPILOT_LLM_MODEL")

    if not api_key:
        missing.append("TESTPILOT_LLM_API_KEY")
    if not base_url:
        missing.append("TESTPILOT_LLM_BASE_URL")
    if not model:
        missing.append("TESTPILOT_LLM_MODEL")

    if missing:
        raise LLMConfigError(
            f"Missing required LLM environment variable(s): {', '.join(missing)}. "
            f"Set them before using --goal."
        )

    # Normalize base_url: strip trailing slash
    base_url = base_url.rstrip("/")  # type: ignore[union-attr]

    return LLMConfig(
        api_key=api_key,  # type: ignore[arg-type]
        base_url=base_url,
        model=model,
    )
