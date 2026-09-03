"""Redaction helpers for JSON Report — T0206.

All redaction functions return a **new** dict/list; they never mutate
the input.  Keys are matched case-insensitively.
"""

from __future__ import annotations

from typing import Any

REDACTED = "[REDACTED]"

# ── Header names (case-insensitive) ─────────────────────────────────────────

_REDACTED_HEADERS: frozenset[str] = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
})

# ── Query param keys (case-insensitive) ─────────────────────────────────────

_REDACTED_QUERY_KEYS: frozenset[str] = frozenset({
    "token",
    "access_token",
    "api_key",
    "apikey",
    "password",
    "secret",
})

# ── Body keys (case-insensitive) ────────────────────────────────────────────

_REDACTED_BODY_KEYS: frozenset[str] = frozenset({
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
})


# ── Public API ──────────────────────────────────────────────────────────────


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact sensitive header values (case-insensitive key match)."""
    return {
        k: REDACTED if k.lower() in _REDACTED_HEADERS else v
        for k, v in headers.items()
    }


def redact_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Redact ALL cookie values."""
    return {k: REDACTED for k in cookies}


def redact_query_params(params: dict[str, str]) -> dict[str, str]:
    """Redact sensitive query parameter values (case-insensitive key match)."""
    return {
        k: REDACTED if k.lower() in _REDACTED_QUERY_KEYS else v
        for k, v in params.items()
    }


def redact_body(value: Any) -> Any:
    """Recursively redact sensitive keys in dicts and lists.

    Non-dict/list values pass through unchanged.
    """
    if isinstance(value, dict):
        return {
            k: REDACTED if k.lower() in _REDACTED_BODY_KEYS else redact_body(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_body(item) for item in value]
    return value
