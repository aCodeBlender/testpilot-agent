"""Tests for T0204: HTTP Executor."""

import json
from unittest.mock import patch

import httpx
import pytest

from testpilot.domain.testing import TestCase
from testpilot.executor.http_executor import HttpExecutor, _parse_body, _safe_error, _is_json_content_type, _apply_body
from testpilot.executor.exceptions import HttpExecutorError


# ── Helpers ──────────────────────────────────────────────────────────────────


def _case(id: str = "tc-1") -> TestCase:
    return TestCase(
        id=id,
        endpoint_id="ep-test",
        scenario_id="sc-test",
        method="GET",
        path="/test",
    )


def _request_data(
    method: str = "GET",
    url: str = "https://api.example.com/test",
    headers: dict | None = None,
    params: dict | None = None,
    cookies: dict | None = None,
    body=None,
) -> dict:
    return {
        "method": method,
        "url": url,
        "headers": headers or {},
        "params": params or {},
        "cookies": cookies or {},
        "body": body,
    }


def _run(handler, request_data: dict | None = None, timeout: float = 10.0):
    """Execute with a MockTransport, bypassing real network."""
    transport = httpx.MockTransport(handler)
    executor = HttpExecutor(timeout_seconds=timeout)
    original_client = httpx.Client

    class MockClient(original_client):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    with patch("testpilot.executor.http_executor.httpx.Client", MockClient):
        return executor.execute(_case(), request_data or _request_data())


def _handler(status_code: int = 200, json_body=None, text_body: str | None = None, content_type: str = "application/json"):
    """Return a handler function for httpx.MockTransport."""
    def handler(request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(
                status_code,
                json=json_body,
                headers={"content-type": content_type},
            )
        if text_body is not None:
            return httpx.Response(
                status_code,
                text=text_body,
                headers={"content-type": content_type},
            )
        return httpx.Response(status_code)
    return handler


# ── Basic responses ─────────────────────────────────────────────────────────


class TestBasicResponses:
    def test_get_200_json(self):
        result = _run(_handler(200, json_body={"status": "ok"}))
        assert result.status_code == 200
        assert result.response_body == {"status": "ok"}
        assert result.response_body_present is True
        assert result.error is None

    def test_post_json_body(self):
        received_body = {}

        def handler(request: httpx.Request):
            received_body.update(json.loads(request.content))
            return httpx.Response(201, json={"created": True})

        result = _run(handler, _request_data(
            method="POST",
            body={"name": "Alice"},
            headers={"content-type": "application/json"},
        ))
        assert result.status_code == 201
        assert received_body == {"name": "Alice"}

    def test_201_response(self):
        result = _run(_handler(201, json_body={"id": 1}))
        assert result.status_code == 201
        assert result.error is None

    def test_400_still_succeeds(self):
        result = _run(_handler(400, json_body={"error": "bad request"}))
        assert result.status_code == 400
        assert result.error is None

    def test_500_still_succeeds(self):
        result = _run(_handler(500, json_body={"error": "internal"}))
        assert result.status_code == 500
        assert result.error is None


# ── Response parsing (try JSON first) ───────────────────────────────────────


class TestResponseParsing:
    def test_json_with_json_content_type(self):
        """application/json + JSON body → dict."""
        result = _run(_handler(200, json_body={"key": "value"}, content_type="application/json"))
        assert result.response_body == {"key": "value"}

    def test_json_with_text_content_type(self):
        """text/plain + JSON body → dict (try JSON first)."""
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                content=b'{"code": 0}',
                headers={"content-type": "text/plain"},
            )
        result = _run(handler)
        assert result.response_body == {"code": 0}

    def test_json_with_no_content_type(self):
        """No Content-Type + JSON body → dict (try JSON first)."""
        def handler(request: httpx.Request):
            return httpx.Response(200, content=b'{"key": "val"}')
        result = _run(handler)
        assert result.response_body == {"key": "val"}

    def test_text_plain_not_json(self):
        """text/plain + plain text → string."""
        result = _run(_handler(200, text_body="hello", content_type="text/plain"))
        assert result.response_body == "hello"

    def test_invalid_json_falls_back_to_text(self):
        """Invalid JSON → response.text."""
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                content=b"not json at all",
                headers={"content-type": "application/json"},
            )
        result = _run(handler)
        assert result.response_body == "not json at all"

    def test_empty_body_204(self):
        """204 No Content → None, body not present."""
        result = _run(_handler(204))
        assert result.response_body is None
        assert result.response_body_present is False

    def test_empty_body_non_204(self):
        """Empty body (non-204) → None, body not present."""
        def handler(request: httpx.Request):
            return httpx.Response(200, content=b"")
        result = _run(handler)
        assert result.response_body is None
        assert result.response_body_present is False

    def test_response_headers_are_plain_dict(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, headers={"x-custom": "val"})
        result = _run(handler)
        assert isinstance(result.response_headers, dict)
        assert result.response_headers["x-custom"] == "val"


# ── Body → httpx mapping ────────────────────────────────────────────────────


class TestBodyMapping:
    def test_json_content_type_dict_body(self):
        """application/json + dict → json= kwarg."""
        received = {}

        def handler(request: httpx.Request):
            received["content"] = request.content
            received["ct"] = request.headers.get("content-type", "")
            return httpx.Response(200, json={"ok": True})

        _run(handler, _request_data(
            method="POST",
            body={"name": "Alice"},
            headers={"content-type": "application/json"},
        ))
        assert json.loads(received["content"]) == {"name": "Alice"}

    def test_json_wildcard_content_type(self):
        """application/vnd.api+json → json= kwarg."""
        received = {}

        def handler(request: httpx.Request):
            received["content"] = request.content
            return httpx.Response(200, json={"ok": True})

        _run(handler, _request_data(
            method="POST",
            body={"x": 1},
            headers={"content-type": "application/vnd.api+json"},
        ))
        assert json.loads(received["content"]) == {"x": 1}

    def test_text_plain_str_body(self):
        """text/plain + str → content= kwarg (raw text)."""
        received = {}

        def handler(request: httpx.Request):
            received["content"] = request.content
            return httpx.Response(200)

        _run(handler, _request_data(
            method="POST",
            body="hello world",
            headers={"content-type": "text/plain"},
        ))
        assert received["content"] == b"hello world"

    def test_text_plain_bytes_body(self):
        """text/plain + bytes → content= kwarg (raw bytes)."""
        received = {}

        def handler(request: httpx.Request):
            received["content"] = request.content
            return httpx.Response(200)

        _run(handler, _request_data(
            method="POST",
            body=b"raw bytes",
            headers={"content-type": "text/plain"},
        ))
        assert received["content"] == b"raw bytes"

    def test_non_json_structured_body_raises_error(self):
        """Non-JSON Content-Type + dict body → HttpExecutorError."""
        def handler(request: httpx.Request):
            return httpx.Response(200)

        with pytest.raises(HttpExecutorError, match="Structured body"):
            _run(handler, _request_data(
                method="POST",
                body={"key": "val"},
                headers={"content-type": "text/plain"},
            ))

    def test_no_content_type_with_dict_body_uses_json(self):
        """No Content-Type header + dict body → json= kwarg (default)."""
        received = {}

        def handler(request: httpx.Request):
            received["content"] = request.content
            return httpx.Response(200, json={"ok": True})

        _run(handler, _request_data(
            method="POST",
            body={"x": 1},
            headers={},
        ))
        assert json.loads(received["content"]) == {"x": 1}


# ── httpx parameter mapping ─────────────────────────────────────────────────


class TestParameterMapping:
    def test_query_params_forwarded(self):
        received_params = {}

        def handler(request: httpx.Request):
            received_params.update(dict(request.url.params))
            return httpx.Response(200)

        _run(handler, _request_data(params={"page": "1", "limit": "10"}))
        assert received_params.get("page") == "1"
        assert received_params.get("limit") == "10"

    def test_cookies_forwarded(self):
        received_cookie_header = None

        def handler(request: httpx.Request):
            nonlocal received_cookie_header
            received_cookie_header = request.headers.get("cookie")
            return httpx.Response(200)

        _run(handler, _request_data(cookies={"session": "abc"}))
        assert received_cookie_header is not None
        assert "session=abc" in received_cookie_header

    def test_custom_headers_forwarded(self):
        received_headers = {}

        def handler(request: httpx.Request):
            received_headers.update(dict(request.headers))
            return httpx.Response(200)

        _run(handler, _request_data(headers={"X-Custom": "val", "Authorization": "Bearer tok"}))
        assert received_headers.get("x-custom") == "val"
        assert received_headers.get("authorization") == "Bearer tok"


# ── Response time ────────────────────────────────────────────────────────────


class TestResponseTime:
    def test_response_time_non_negative(self):
        result = _run(_handler(200, json_body={}))
        assert result.response_time_ms is not None
        assert result.response_time_ms >= 0


# ── Transport errors ─────────────────────────────────────────────────────────


class TestTransportErrors:
    def test_timeout(self):
        def handler(request: httpx.Request):
            raise httpx.TimeoutException("timed out")
        result = _run(handler)
        assert result.status_code is None
        assert result.error is not None
        assert "Timeout" in result.error

    def test_connect_error(self):
        def handler(request: httpx.Request):
            raise httpx.ConnectError("connection refused")
        result = _run(handler)
        assert result.status_code is None
        assert result.error is not None
        assert "ConnectError" in result.error

    def test_error_does_not_leak_auth_token(self):
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")
        result = _run(
            handler,
            _request_data(headers={"Authorization": "Bearer super-secret-token-123"}),
        )
        assert "super-secret-token-123" not in (result.error or "")

    def test_error_does_not_leak_request_data(self):
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")
        result = _run(handler, _request_data(body={"password": "s3cret"}))
        assert "s3cret" not in (result.error or "")

    def test_transport_error_has_response_time(self):
        def handler(request: httpx.Request):
            raise httpx.TimeoutException("timeout")
        result = _run(handler)
        assert result.response_time_ms is not None
        assert result.response_time_ms >= 0


# ── URL sanitization ────────────────────────────────────────────────────────


class TestURLSanitization:
    def test_query_token_not_leaked(self):
        """URL with token in query must be sanitized."""
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")
        result = _run(
            handler,
            _request_data(url="https://api.example.com/users?token=secret123"),
        )
        assert "secret123" not in (result.error or "")
        assert "api.example.com" in (result.error or "")

    def test_api_key_not_leaked(self):
        """URL with api_key in query must be sanitized."""
        def handler(request: httpx.Request):
            raise httpx.TimeoutException("timeout")
        result = _run(
            handler,
            _request_data(url="https://example.com/data?api_key=sk-abc123"),
        )
        assert "sk-abc123" not in (result.error or "")

    def test_userinfo_not_leaked(self):
        """URL with userinfo must be sanitized."""
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")
        result = _run(
            handler,
            _request_data(url="https://user:pass@example.com/api"),
        )
        assert "user" not in (result.error or "")
        assert "pass" not in (result.error or "")

    def test_fragment_not_leaked(self):
        """URL with fragment must be sanitized."""
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")
        result = _run(
            handler,
            _request_data(url="https://example.com/api?token=x#secret"),
        )
        assert "#secret" not in (result.error or "")

    def test_clean_url_preserved(self):
        """Clean URL path is preserved in error."""
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")
        result = _run(
            handler,
            _request_data(url="https://example.com/users/123"),
        )
        assert "https://example.com/users/123" in (result.error or "")


# ── Redirect ─────────────────────────────────────────────────────────────────


class TestRedirect:
    def test_redirect_not_followed(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                302,
                headers={"Location": "https://api.example.com/new"},
            )
        result = _run(handler)
        assert result.status_code == 302
        assert result.response_headers.get("location") == "https://api.example.com/new"


# ── Immutability ─────────────────────────────────────────────────────────────


class TestImmutability:
    def test_does_not_mutate_request_data(self):
        req = _request_data(
            headers={"X-Test": "val", "content-type": "application/json"},
            params={"q": "1"},
            cookies={"s": "v"},
            body={"name": "Alice"},
        )
        orig = json.dumps(req, sort_keys=True)
        _run(_handler(200, json_body={}), req)
        assert json.dumps(req, sort_keys=True) == orig


# ── Stability ────────────────────────────────────────────────────────────────


class TestStability:
    def test_same_mock_same_result(self):
        handler = _handler(200, json_body={"key": "value"})
        r1 = _run(handler)
        r2 = _run(handler)
        assert r1.status_code == r2.status_code
        assert r1.response_body == r2.response_body
        assert r1.error == r2.error


# ── Helper unit tests ────────────────────────────────────────────────────────


class TestHelpers:
    def test_parse_body_json(self):
        resp = httpx.Response(200, json={"a": 1}, headers={"content-type": "application/json"})
        assert _parse_body(resp) == {"a": 1}

    def test_parse_body_text(self):
        resp = httpx.Response(200, text="hi", headers={"content-type": "text/plain"})
        assert _parse_body(resp) == "hi"

    def test_parse_body_204(self):
        resp = httpx.Response(204)
        assert _parse_body(resp) is None

    def test_parse_body_empty(self):
        resp = httpx.Response(200, content=b"")
        assert _parse_body(resp) is None

    def test_is_json_content_type_true(self):
        assert _is_json_content_type({"Content-Type": "application/json"}) is True

    def test_is_json_content_type_wildcard(self):
        assert _is_json_content_type({"content-type": "application/vnd.api+json"}) is True

    def test_is_json_content_type_false(self):
        assert _is_json_content_type({"content-type": "text/plain"}) is False

    def test_is_json_content_type_missing(self):
        assert _is_json_content_type({}) is False

    def test_safe_error_sanitized(self):
        msg = _safe_error(
            httpx.ConnectError("x"),
            "https://user:pass@example.com/path?token=abc#frag",
        )
        assert "user" not in msg
        assert "pass" not in msg
        assert "token" not in msg
        assert "abc" not in msg
        assert "frag" not in msg
        assert "https://example.com/path" in msg

    def test_apply_body_json(self):
        kw = {}
        _apply_body(kw, {"x": 1}, {"content-type": "application/json"})
        assert kw["json"] == {"x": 1}

    def test_apply_body_text_str(self):
        kw = {}
        _apply_body(kw, "hello", {"content-type": "text/plain"})
        assert kw["content"] == "hello"

    def test_apply_body_text_bytes(self):
        kw = {}
        _apply_body(kw, b"raw", {"content-type": "text/plain"})
        assert kw["content"] == b"raw"

    def test_apply_body_non_json_structured_raises(self):
        with pytest.raises(HttpExecutorError):
            _apply_body({}, {"x": 1}, {"content-type": "text/plain"})
