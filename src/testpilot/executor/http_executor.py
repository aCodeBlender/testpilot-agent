"""HttpExecutor — T0204.

Executes HTTP requests via httpx and records objective results
in ``ExecutionResult``.  Does **not** judge pass/fail — that is
the Validator's job (T0205).
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from testpilot.domain.testing import TestCase, ExecutionResult
from testpilot.executor.exceptions import HttpExecutorError


class HttpExecutor:
    """Synchronous HTTP executor backed by ``httpx.Client``.

    Parameters
    ----------
    timeout_seconds:
        Per-request timeout in seconds.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    # ── public API ────────────────────────────────────────────────────────

    def execute(
        self,
        case: TestCase,
        request_data: dict[str, Any],
    ) -> ExecutionResult:
        """Execute one HTTP request and return an ``ExecutionResult``.

        Parameters
        ----------
        case:
            The test case (used only for ``case.id``).
        request_data:
            Output of ``RequestBuilder.build()`` — keys: ``method``,
            ``url``, ``headers``, ``params``, ``cookies``, ``body``.

        Returns
        -------
        ExecutionResult
            Always returns a result, even on transport errors.

        Raises
        ------
        HttpExecutorError
            If body is structured (dict/list) but Content-Type is not JSON.
        """
        method = request_data["method"]
        url = request_data["url"]
        headers = request_data.get("headers", {})
        params = request_data.get("params", {})
        cookies = request_data.get("cookies", {})
        body = request_data.get("body")

        # Build httpx kwargs
        httpx_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "follow_redirects": False,
        }

        # Map body to httpx parameter based on Content-Type
        if body is not None:
            _apply_body(httpx_kwargs, body, headers)

        t0 = time.perf_counter()
        try:
            with httpx.Client(
                cookies=cookies,
                timeout=self._timeout,
            ) as client:
                response = client.request(**httpx_kwargs)
        except httpx.TimeoutException as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ExecutionResult(
                case_id=case.id,
                status_code=None,
                response_headers={},
                response_body=None,
                response_time_ms=round(elapsed_ms, 2),
                error=f"Timeout: {_safe_error(exc, url)}",
            )
        except httpx.RequestError as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ExecutionResult(
                case_id=case.id,
                status_code=None,
                response_headers={},
                response_body=None,
                response_time_ms=round(elapsed_ms, 2),
                error=f"{type(exc).__name__}: {_safe_error(exc, url)}",
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Parse response
        response_headers = dict(response.headers)
        body_present = bool(response.content)
        response_body = _parse_body(response)

        return ExecutionResult(
            case_id=case.id,
            status_code=response.status_code,
            response_headers=response_headers,
            response_body=response_body,
            response_body_present=body_present,
            response_time_ms=round(elapsed_ms, 2),
            error=None,
        )


# ── helpers ────────────────────────────────────────────────────────────────


def _is_json_content_type(headers: dict[str, str]) -> bool:
    """Check if Content-Type indicates JSON (case-insensitive)."""
    ct = ""
    for k, v in headers.items():
        if k.lower() == "content-type":
            ct = v.lower()
            break
    if not ct:
        return False
    return "application/json" in ct or ct.endswith("+json")


def _apply_body(
    httpx_kwargs: dict[str, Any],
    body: Any,
    headers: dict[str, str],
) -> None:
    """Map *body* to the correct httpx keyword argument.

    Raises ``HttpExecutorError`` when body is structured but Content-Type
    is explicitly non-JSON (V1 does not implement form-data / XML serialization).
    """
    has_ct = any(k.lower() == "content-type" for k in headers)

    if not has_ct or _is_json_content_type(headers):
        httpx_kwargs["json"] = body
        return

    # Explicit non-JSON Content-Type
    if isinstance(body, (str, bytes)):
        httpx_kwargs["content"] = body
        return

    # Structured body (dict/list) with explicit non-JSON Content-Type — unsupported in V1
    raise HttpExecutorError(
        f"Structured body (type={type(body).__name__}) requires JSON Content-Type, "
        f"got '{headers.get('content-type', '')}'"
    )


def _parse_body(response: httpx.Response) -> Any:
    """Parse response body.

    Strategy: try JSON first (regardless of Content-Type), fall back to text.
    Returns ``None`` when the body is empty or status is 204.
    """
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except Exception:
        return response.text


def _safe_error(exc: Exception, url: str) -> str:
    """Build an error string with a sanitized URL.

    Strips userinfo, query string, and fragment so that tokens / API keys
    in the URL are never written to ExecutionResult.error.
    """
    parsed = urlparse(url)
    # Strip userinfo (user:pass@) from netloc
    hostname = parsed.hostname or parsed.netloc
    port = parsed.port
    netloc = f"{hostname}:{port}" if port else hostname
    sanitized = urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
    return f"{type(exc).__name__} on {sanitized}: {exc}"
