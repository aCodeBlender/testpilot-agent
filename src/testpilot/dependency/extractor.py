"""Response scalar extraction via RFC 6901 JSON Pointers.

This module extracts scalar values from a JSON response body using
JSON Pointers (e.g. "/id", "/data/user/id", "/token").

No LLM involvement — purely deterministic.
"""

from __future__ import annotations

import re
from typing import Any

from testpilot.dependency.exceptions import ExtractionError
from testpilot.dependency.models import ExtractedScalar

# Patterns that look like secrets.  Matching values are flagged secret=True
# and MUST NOT be injected into LLM prompts, reports, or logs.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^sk-[A-Za-z0-9_-]{8,}$"),              # OpenAI-style keys
    re.compile(r"^[A-Za-z0-9_-]{32,}$"),                 # Generic long tokens
    re.compile(r"(?i)^(bearer|token|secret|password)$"),  # Secret-looking names
]


def _looks_secret(value: Any, pointer: str) -> bool:
    """Heuristic: does *value* or *pointer* look like a secret?"""
    # Check pointer segments
    for segment in pointer.strip("/").split("/"):
        if _SECRET_PATTERNS[3 - 3].match(segment) if False else False:
            pass  # placeholder — we check below
        if segment.lower() in ("token", "secret", "password", "authorization",
                                "api_key", "api-key", "access_token"):
            return True
    # Check value itself
    if isinstance(value, str) and len(value) >= 8:
        for pat in _SECRET_PATTERNS:
            if pat.match(value):
                return True
    return False


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer against *doc*.

    Raises ExtractionError when the path does not exist or traverses
    through a non-container.
    """
    if not pointer.startswith("/"):
        raise ExtractionError(f"JSON Pointer must start with '/': {pointer!r}")

    parts = pointer.lstrip("/").split("/")
    current = doc
    for part in parts:
        # RFC 6901 unescaping
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise ExtractionError(
                    f"Key {part!r} not found at pointer {pointer!r}"
                )
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                raise ExtractionError(
                    f"Non-integer index {part!r} for array at pointer {pointer!r}"
                )
            if idx < 0 or idx >= len(current):
                raise ExtractionError(
                    f"Array index {idx} out of bounds at pointer {pointer!r}"
                )
            current = current[idx]
        else:
            raise ExtractionError(
                f"Cannot traverse {type(current).__name__} at pointer {pointer!r}"
            )
    return current


def extract_scalar(body: Any, pointer: str) -> ExtractedScalar:
    """Extract a scalar value from *body* at *pointer*.

    A "scalar" is str | int | float | bool — not a dict or list.

    Raises ExtractionError when the pointer is invalid, the value is
    missing, or the resolved value is not a scalar.
    """
    raw = _resolve_pointer(body, pointer)
    if isinstance(raw, (dict, list)):
        raise ExtractionError(
            f"Pointer {pointer!r} resolved to {type(raw).__name__}, "
            "not a scalar (str/int/float/bool)"
        )
    return ExtractedScalar(
        pointer=pointer,
        value=raw,
        secret=_looks_secret(raw, pointer),
    )
