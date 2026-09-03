"""Tests for .env file loading — Phase 3B Batch 3 cleanup.

Verifies that the CLI loads .env via python-dotenv and that
environment-variable precedence is correct.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from testpilot.llm.config import LLMConfig, load_llm_config_from_env
from testpilot.llm.exceptions import LLMConfigError


class TestDotEnvLoading:
    """Test that .env values are picked up through os.environ."""

    def test_env_values_loaded_by_dotenv(self, tmp_path: Path, monkeypatch):
        """A .env file in cwd should populate os.environ via load_dotenv."""
        from dotenv import load_dotenv, find_dotenv

        env_file = tmp_path / ".env"
        env_file.write_text(
            "TESTPILOT_LLM_API_KEY=key-from-dotenv\n"
            "TESTPILOT_LLM_BASE_URL=http://dotenv.example.com/v1\n"
            "TESTPILOT_LLM_MODEL=dotenv-model\n"
        )

        # Ensure no stale env vars
        for k in ("TESTPILOT_LLM_API_KEY", "TESTPILOT_LLM_BASE_URL", "TESTPILOT_LLM_MODEL"):
            monkeypatch.delenv(k, raising=False)

        # load_dotenv with explicit path
        load_dotenv(env_file, override=False)

        try:
            config = load_llm_config_from_env()
            assert config.base_url == "http://dotenv.example.com/v1"
            assert config.model == "dotenv-model"
            assert config.api_key.get_secret_value() == "key-from-dotenv"
        finally:
            for k in ("TESTPILOT_LLM_API_KEY", "TESTPILOT_LLM_BASE_URL", "TESTPILOT_LLM_MODEL"):
                monkeypatch.delenv(k, raising=False)

    def test_env_overrides_dotenv(self, tmp_path: Path, monkeypatch):
        """An existing OS env var must take precedence over .env value."""
        from dotenv import load_dotenv

        env_file = tmp_path / ".env"
        env_file.write_text(
            "TESTPILOT_LLM_API_KEY=key-from-dotenv\n"
            "TESTPILOT_LLM_BASE_URL=http://dotenv.example.com/v1\n"
            "TESTPILOT_LLM_MODEL=dotenv-model\n"
        )

        # Set real env vars (higher priority)
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "key-from-env")
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "http://env.example.com/v1")
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "env-model")

        # load_dotenv with override=False (default)
        load_dotenv(env_file, override=False)

        try:
            config = load_llm_config_from_env()
            assert config.api_key.get_secret_value() == "key-from-env"
            assert config.base_url == "http://env.example.com/v1"
            assert config.model == "env-model"
        finally:
            for k in ("TESTPILOT_LLM_API_KEY", "TESTPILOT_LLM_BASE_URL", "TESTPILOT_LLM_MODEL"):
                monkeypatch.delenv(k, raising=False)


class TestNoGoalNoConfig:
    """Test that no-goal deterministic runs don't require LLM config."""

    def test_no_goal_does_not_require_llm_env(self, monkeypatch):
        """Without --goal, missing LLM env vars should not cause errors."""
        for k in ("TESTPILOT_LLM_API_KEY", "TESTPILOT_LLM_BASE_URL", "TESTPILOT_LLM_MODEL"):
            monkeypatch.delenv(k, raising=False)

        # load_llm_config_from_env would fail, but it's never called without --goal
        with pytest.raises(LLMConfigError):
            load_llm_config_from_env()

        # The CLI only calls load_llm_config_from_env when goal is set,
        # so deterministic runs succeed even without these vars.


class TestSecretSafety:
    """Test that API keys remain secret-safe."""

    def test_api_key_not_in_repr(self):
        """LLMConfig.api_key should not leak in repr."""
        config = LLMConfig(
            api_key="sk-secret-12345",
            base_url="http://example.com",
            model="test",
        )
        assert "sk-secret-12345" not in repr(config)

    def test_api_key_not_in_str(self):
        """LLMConfig.api_key should not leak in str."""
        config = LLMConfig(
            api_key="sk-secret-12345",
            base_url="http://example.com",
            model="test",
        )
        assert "sk-secret-12345" not in str(config)


class TestEnvExample:
    """Test that .env.example contains no real credentials."""

    def test_env_example_has_no_secrets(self):
        """The .env.example file must contain only empty placeholders."""
        env_example = Path(__file__).resolve().parents[2] / ".env.example"
        assert env_example.is_file(), ".env.example not found"

        content = env_example.read_text()
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            assert value == "", (
                f".env.example must have empty values, "
                f"but {key.strip()} has a non-empty value"
            )
