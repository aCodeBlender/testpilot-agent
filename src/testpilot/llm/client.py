"""OpenAI-compatible LLM client — thin wrapper using httpx.

Sends a chat completion request and returns the assistant's text content.
No SDK dependency — just httpx.
"""

from __future__ import annotations

import httpx

from testpilot.llm.config import LLMConfig
from testpilot.llm.exceptions import LLMError, LLMResponseError


class OpenAICompatibleLLMClient:
    """Minimal client for OpenAI-compatible chat completion endpoints.

    Parameters
    ----------
    config:
        LLM configuration (api_key as SecretStr, base_url, model, timeout).
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def call(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat completion request and return the assistant's text.

        Parameters
        ----------
        system_prompt:
            System message content.
        user_prompt:
            User message content.

        Returns
        -------
        str
            The assistant's text response.

        Raises
        ------
        LLMError
            On transport errors, HTTP errors, or invalid responses.
        LLMResponseError
            If the response cannot be parsed or has no content.
        """
        url = f"{self._config.base_url}/chat/completions"
        # Unwrap SecretStr only at the HTTP boundary
        raw_key = self._config.api_key.get_secret_value()
        headers = {
            "Authorization": f"Bearer {raw_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
        }

        try:
            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError(f"LLM request timed out after {self._config.timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM transport error: {exc}") from exc

        if response.status_code != 200:
            # Sanitize: never include Authorization header in error
            raise LLMError(
                f"LLM HTTP error {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise LLMResponseError("LLM response is not valid JSON") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                f"LLM response missing expected structure: "
                f"{list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM returned empty content")

        return content
