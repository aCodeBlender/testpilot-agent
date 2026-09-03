"""Tests for T0203: Request Builder."""

import pytest

from testpilot.domain.testing import TestCase
from testpilot.executor.request_builder import RequestBuilder
from testpilot.executor.exceptions import RequestBuildError


# ── Helpers ──────────────────────────────────────────────────────────────────


def _case(
    id: str = "tc-1",
    method: str = "GET",
    path: str = "/users",
    headers=None,
    query_params=None,
    path_params=None,
    cookies=None,
    body=None,
) -> TestCase:
    return TestCase(
        id=id,
        endpoint_id="ep-test",
        scenario_id="sc-test",
        method=method,
        path=path,
        headers=headers or {},
        query_params=query_params or {},
        path_params=path_params or {},
        cookies=cookies or {},
        body=body,
    )


def _builder(base_url="https://api.example.com", bearer_token=None, custom_headers=None):
    return RequestBuilder(base_url=base_url, bearer_token=bearer_token, custom_headers=custom_headers)


# ── URL resolution ───────────────────────────────────────────────────────────


class TestURLResolution:
    def test_simple_path(self):
        req = _builder().build(_case(path="/users"))
        assert req["url"] == "https://api.example.com/users"

    def test_base_url_trailing_slash(self):
        req = _builder(base_url="https://api.example.com/").build(_case(path="/users"))
        assert req["url"] == "https://api.example.com/users"

    def test_path_substitution(self):
        req = _builder().build(
            _case(path="/users/{id}", path_params={"id": "42"})
        )
        assert req["url"] == "https://api.example.com/users/42"

    def test_url_encoded_path_param(self):
        """Path params with special chars must be URL-encoded."""
        req = _builder().build(
            _case(path="/users/{name}", path_params={"name": "hello world"})
        )
        assert req["url"] == "https://api.example.com/users/hello%20world"

    def test_url_encoded_slash_in_path_param(self):
        """Slashes in path params must be encoded, not treated as path separators."""
        req = _builder().build(
            _case(path="/files/{path}", path_params={"path": "a/b/c"})
        )
        assert req["url"] == "https://api.example.com/files/a%2Fb%2Fc"

    def test_multi_segment_path(self):
        req = _builder().build(
            _case(path="/users/{id}/posts/{pid}", path_params={"id": "1", "pid": "99"})
        )
        assert req["url"] == "https://api.example.com/users/1/posts/99"


# ── Headers ──────────────────────────────────────────────────────────────────


class TestHeaders:
    def test_custom_headers(self):
        req = _builder().build(
            _case(headers={"X-Custom": "value"})
        )
        assert req["headers"]["X-Custom"] == "value"

    def test_bearer_token_added(self):
        req = _builder(bearer_token="tok-123").build(_case())
        assert req["headers"]["Authorization"] == "Bearer tok-123"

    def test_bearer_token_overrides_custom_auth(self):
        """Custom case headers + bearer_token: bearer_token wins."""
        req = _builder(bearer_token="tok-new").build(
            _case(headers={"Authorization": "Bearer old"})
        )
        assert req["headers"]["Authorization"] == "Bearer tok-new"

    def test_custom_headers_without_bearer(self):
        req = _builder().build(
            _case(headers={"X-Requested-With": "XMLHttpRequest"})
        )
        assert req["headers"]["X-Requested-With"] == "XMLHttpRequest"

    def test_missing_auth_strips_bearer_token(self):
        """missing_auth=True must remove Authorization even if bearer_token is set."""
        req = _builder(bearer_token="tok-123").build(_case(), is_missing_auth=True)
        assert "Authorization" not in req["headers"]

    def test_missing_auth_strips_custom_auth_case_insensitive(self):
        """All Authorization variants (any case) must be removed."""
        req = _builder(bearer_token="tok-123").build(
            _case(headers={"authorization": "Bearer from-case"}),
            is_missing_auth=True,
        )
        auth_keys = [k for k in req["headers"] if k.lower() == "authorization"]
        assert len(auth_keys) == 0

    def test_missing_auth_strips_uppercase(self):
        req = _builder().build(
            _case(headers={"AUTHORIZATION": "Bearer upper"}),
            is_missing_auth=True,
        )
        auth_keys = [k for k in req["headers"] if k.lower() == "authorization"]
        assert len(auth_keys) == 0


# ── Query params ─────────────────────────────────────────────────────────────


class TestQueryParams:
    def test_query_params_passed_as_params(self):
        req = _builder().build(
            _case(query_params={"page": "1", "limit": "10"})
        )
        assert req["params"] == {"page": "1", "limit": "10"}

    def test_empty_query_params(self):
        req = _builder().build(_case(query_params={}))
        assert req["params"] == {}


# ── Cookies ──────────────────────────────────────────────────────────────────


class TestCookies:
    def test_cookies_passed_through(self):
        req = _builder().build(
            _case(cookies={"session": "abc123", "prefs": "x"})
        )
        assert req["cookies"] == {"session": "abc123", "prefs": "x"}

    def test_cookies_default_empty(self):
        req = _builder().build(_case())
        assert req["cookies"] == {}

    def test_cookies_not_in_headers(self):
        """Cookies must be in a separate dict, not in Cookie header."""
        req = _builder().build(
            _case(cookies={"session": "abc"})
        )
        assert "Cookie" not in req.get("headers", {})


# ── Body ─────────────────────────────────────────────────────────────────────


class TestBody:
    def test_body_passthrough(self):
        req = _builder().build(
            _case(method="POST", body={"name": "Alice"})
        )
        assert req["body"] == {"name": "Alice"}

    def test_body_none(self):
        req = _builder().build(_case(body=None))
        assert req["body"] is None


# ── Method ───────────────────────────────────────────────────────────────────


class TestMethod:
    def test_get_method(self):
        req = _builder().build(_case(method="GET"))
        assert req["method"] == "GET"

    def test_post_method(self):
        req = _builder().build(_case(method="POST"))
        assert req["method"] == "POST"


# ── Immutability ─────────────────────────────────────────────────────────────


class TestImmutability:
    def test_does_not_mutate_test_case(self):
        tc = _case(
            headers={"X-Custom": "value"},
            query_params={"page": "1"},
            path_params={"id": "42"},
            cookies={"session": "abc"},
        )
        orig_headers = dict(tc.headers)
        orig_query = dict(tc.query_params)
        orig_path = dict(tc.path_params)
        orig_cookies = dict(tc.cookies)

        _builder(bearer_token="tok").build(tc)

        assert tc.headers == orig_headers
        assert tc.query_params == orig_query
        assert tc.path_params == orig_path
        assert tc.cookies == orig_cookies


# ── Output structure ────────────────────────────────────────────────────────


class TestOutputStructure:
    def test_required_keys(self):
        req = _builder().build(_case())
        assert "method" in req
        assert "url" in req
        assert "headers" in req
        assert "cookies" in req
        assert "body" in req

    def test_types(self):
        req = _builder().build(
            _case(method="POST", body={"x": 1}, cookies={"s": "v"})
        )
        assert isinstance(req["method"], str)
        assert isinstance(req["url"], str)
        assert isinstance(req["headers"], dict)
        assert isinstance(req["cookies"], dict)
