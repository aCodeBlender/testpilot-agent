"""OpenAPI Loader — loads and resolves an OpenAPI spec via Prance.

Input:  openapi_source (URL or local file path)
Output: resolved OpenAPI dict (all $ref expanded, validated)

This module does NOT create domain models — that is the Mapper's job.
"""

from __future__ import annotations

import os

from prance import ResolvingParser

from testpilot.openapi.exceptions import LoaderError


def load_openapi(source: str) -> dict:
    """Load and resolve an OpenAPI spec from *source*.

    Parameters
    ----------
    source:
        An HTTP(S) URL, or a local file path to a YAML/JSON OpenAPI spec.

    Returns
    -------
    dict
        The fully resolved OpenAPI specification as a plain dict.

    Raises
    ------
    LoaderError
        If the file does not exist, the URL is unreachable, the content
        is not valid YAML/JSON, or the OpenAPI spec is invalid.
    """
    # ── Basic validation ────────────────────────────────────────────────
    if not source or not source.strip():
        raise LoaderError("openapi_source must not be empty")

    is_url = source.strip().lower().startswith(("http://", "https://"))

    if not is_url:
        expanded = os.path.expanduser(source.strip())
        if not os.path.exists(expanded):
            raise LoaderError(f"File not found: {expanded}")
        source = expanded

    # ── Prance parse + resolve + validate ───────────────────────────────
    try:
        parser = ResolvingParser(source)
    except FileNotFoundError as exc:
        raise LoaderError(f"File not found: {source}") from exc
    except Exception as exc:
        # Prance raises various exceptions (URLError, UnicodeDecodeError,
        # prance exceptions, etc.) — wrap them all uniformly.
        raise LoaderError(f"Failed to load OpenAPI spec from '{source}': {exc}") from exc

    spec: dict | None = parser.specification
    if not isinstance(spec, dict):
        raise LoaderError(
            f"Prance returned non-dict result ({type(spec).__name__}) for '{source}'"
        )

    return spec
