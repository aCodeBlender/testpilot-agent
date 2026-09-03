"""Unit tests for LLM Config + Client — T0301 + cleanup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from testpilot.llm.client import OpenAICompatibleLLMClient
from testpilot.llm.config import LLMConfig, load_llm_config_from_env
from testpilot.llm.exceptions import LLMConfigError, LLMError, LLMResponseError


# ── LLMConfig ────────────────────────────────────────────────────────────────


class TestLLMConfig:
    def test_construction(self):
        cfg = LLMConfig(
            api_key=SecretStr("sk-test"),
            base_url="https://api.example.com/v1",
            model="gpt-4",
        )
        assert cfg.base_url == "https://api.example.com/v1"
        assert cfg.model == "gpt-4"
        assert cfg.timeout_seconds == 30.0

    def test_api_key_secret_str(self):
        cfg = LLMConfig(
            api_key=SecretStr("sk-secret-12345"),
            base_url="https://x.com/v1",
            model="m",
        )
        # SecretStr hides the value
        r = repr(cfg)
        assert "sk-secret-12345" not in r
        s = str(cfg)
        assert "sk-secret-12345" not in s

    def test_api_key_not_in_model_dump(self):
        cfg = LLMConfig(
            api_key=SecretStr("sk-leaked"),
            base_url="https://x.com/v1",
            model="m",
        )
        d = cfg.model_dump()
        # SecretStr serializes to **********
        assert "sk-leaked" not in str(d)

    def test_timeout_must_be_positive(self):
        with pytest.raises(Exception):
            LLMConfig(
                api_key=SecretStr("sk-test"),
                base_url="https://x.com/v1",
                model="m",
                timeout_seconds=0,
            )


# ── load_llm_config_from_env ─────────────────────────────────────────────────


class TestLoadLLMConfigFromEnv:
    def _set_all(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-env-key")
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://custom.api.com/v1")
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "gpt-4")

    def test_loads_from_env(self, monkeypatch):
        self._set_all(monkeypatch)
        cfg = load_llm_config_from_env()
        assert cfg.api_key.get_secret_value() == "sk-env-key"
        assert cfg.base_url == "https://custom.api.com/v1"
        assert cfg.model == "gpt-4"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("TESTPILOT_LLM_API_KEY", raising=False)
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://x.com/v1")
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "m")
        with pytest.raises(LLMConfigError, match="TESTPILOT_LLM_API_KEY"):
            load_llm_config_from_env()

    def test_missing_base_url_raises(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-key")
        monkeypatch.delenv("TESTPILOT_LLM_BASE_URL", raising=False)
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "m")
        with pytest.raises(LLMConfigError, match="TESTPILOT_LLM_BASE_URL"):
            load_llm_config_from_env()

    def test_missing_model_raises(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-key")
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://x.com/v1")
        monkeypatch.delenv("TESTPILOT_LLM_MODEL", raising=False)
        with pytest.raises(LLMConfigError, match="TESTPILOT_LLM_MODEL"):
            load_llm_config_from_env()

    def test_all_missing_reports_all(self, monkeypatch):
        monkeypatch.delenv("TESTPILOT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("TESTPILOT_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("TESTPILOT_LLM_MODEL", raising=False)
        with pytest.raises(LLMConfigError, match="TESTPILOT_LLM_API_KEY") as exc_info:
            load_llm_config_from_env()
        msg = str(exc_info.value)
        assert "TESTPILOT_LLM_BASE_URL" in msg
        assert "TESTPILOT_LLM_MODEL" in msg

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-key")
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://api.example.com/v1/")
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "m")
        cfg = load_llm_config_from_env()
        assert cfg.base_url == "https://api.example.com/v1"

    def test_secret_not_in_error(self, monkeypatch):
        """API key must never appear in exception messages."""
        monkeypatch.delenv("TESTPILOT_LLM_API_KEY", raising=False)
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://x.com/v1")
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "m")
        with pytest.raises(LLMConfigError) as exc_info:
            load_llm_config_from_env()
        assert "sk-" not in str(exc_info.value)


# ── OpenAICompatibleLLMClient ────────────────────────────────────────────────


class TestLLMClient:
    def _make_config(self) -> LLMConfig:
        return LLMConfig(
            api_key=SecretStr("sk-test-key"),
            base_url="https://api.test.com/v1",
            model="test-model",
        )

    def test_call_returns_content(self):
        cfg = self._make_config()
        client = OpenAICompatibleLLMClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"result": "ok"}'}}]
        }

        with patch("testpilot.llm.client.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = client.call("system", "user")
            assert result == '{"result": "ok"}'

    def test_call_http_error_raises(self):
        cfg = self._make_config()
        client = OpenAICompatibleLLMClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("testpilot.llm.client.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            with pytest.raises(LLMError, match="401"):
                client.call("system", "user")

    def test_call_timeout_raises(self):
        cfg = self._make_config()
        client = OpenAICompatibleLLMClient(cfg)

        with patch("testpilot.llm.client.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_client_cls.return_value = mock_client

            with pytest.raises(LLMError, match="timed out"):
                client.call("system", "user")

    def test_api_key_not_in_exception(self):
        """API key must never appear in exception messages."""
        cfg = self._make_config()
        client = OpenAICompatibleLLMClient(cfg)

        with patch("testpilot.llm.client.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.HTTPError("connection failed")
            mock_client_cls.return_value = mock_client

            with pytest.raises(LLMError) as exc_info:
                client.call("system", "user")
            assert "sk-test-key" not in str(exc_info.value)

    def test_sends_correct_headers(self):
        cfg = self._make_config()
        client = OpenAICompatibleLLMClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }

        with patch("testpilot.llm.client.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            client.call("sys", "usr")

            call_kwargs = mock_client.post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers["Authorization"] == "Bearer sk-test-key"
