"""Tests for T0112: OpenAPI Loader (Prance integration)."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml

from testpilot.openapi.loader import load_openapi
from testpilot.openapi.exceptions import LoaderError


# ── Fixtures ────────────────────────────────────────────────────────────────

MINIMAL_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Minimal API", "version": "1.0.0"},
    "paths": {},
}

SPEC_WITH_GET = {
    "openapi": "3.0.3",
    "info": {"title": "Get API", "version": "1.0.0"},
    "paths": {
        "/ping": {
            "get": {
                "operationId": "ping",
                "summary": "Health check",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}

SPEC_WITH_REF = {
    "openapi": "3.0.3",
    "info": {"title": "Ref API", "version": "1.0.0"},
    "paths": {
        "/users": {
            "post": {
                "operationId": "createUser",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserInput"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        },
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "UserInput": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "email": {"type": "string", "format": "email"},
                },
            },
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
        }
    },
}

INVALID_SPEC = {
    "openapi": "3.0.3",
    # Missing required "info" field — Prance should reject this.
    "paths": {},
}


def _write_temp(spec: dict, suffix: str = ".json") -> str:
    """Write *spec* to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    if suffix == ".yaml":
        yaml.dump(spec, f)
    else:
        json.dump(spec, f)
    f.close()
    return f.name


# ── Tests ───────────────────────────────────────────────────────────────────


class TestLoaderJSON:
    def test_load_json_file(self):
        path = _write_temp(MINIMAL_SPEC, ".json")
        try:
            result = load_openapi(path)
            assert result["info"]["title"] == "Minimal API"
        finally:
            os.unlink(path)

    def test_load_json_with_endpoints(self):
        path = _write_temp(SPEC_WITH_GET, ".json")
        try:
            result = load_openapi(path)
            assert "/ping" in result["paths"]
            assert "get" in result["paths"]["/ping"]
        finally:
            os.unlink(path)


class TestLoaderYAML:
    def test_load_yaml_file(self):
        path = _write_temp(MINIMAL_SPEC, ".yaml")
        try:
            result = load_openapi(path)
            assert result["info"]["title"] == "Minimal API"
        finally:
            os.unlink(path)

    def test_load_yaml_with_endpoints(self):
        path = _write_temp(SPEC_WITH_GET, ".yaml")
        try:
            result = load_openapi(path)
            assert "/ping" in result["paths"]
        finally:
            os.unlink(path)


class TestLoaderRefResolution:
    def test_ref_resolved(self):
        """Prance must resolve $ref so the Mapper gets inline schemas."""
        path = _write_temp(SPEC_WITH_REF, ".json")
        try:
            result = load_openapi(path)
            post = result["paths"]["/users"]["post"]
            # requestBody schema should be resolved (no $ref key).
            rb_schema = post["requestBody"]["content"]["application/json"]["schema"]
            assert "properties" in rb_schema
            assert "name" in rb_schema["properties"]
            # response schema should be resolved.
            resp_schema = (
                post["responses"]["201"]["content"]["application/json"]["schema"]
            )
            assert "properties" in resp_schema
            assert "id" in resp_schema["properties"]
        finally:
            os.unlink(path)


class TestLoaderURL:
    @patch("testpilot.openapi.loader.ResolvingParser")
    def test_https_url_passed_to_prance(self, mock_parser_cls):
        """HTTPS URL must be passed directly to Prance, not treated as local path."""
        mock_parser = MagicMock()
        mock_parser.specification = {"openapi": "3.0.3", "info": {"title": "X", "version": "1"}}
        mock_parser_cls.return_value = mock_parser

        result = load_openapi("https://example.com/openapi.json")

        mock_parser_cls.assert_called_once_with("https://example.com/openapi.json")
        assert result["openapi"] == "3.0.3"

    @patch("testpilot.openapi.loader.ResolvingParser")
    def test_http_url_passed_to_prance(self, mock_parser_cls):
        """HTTP URL must also be passed directly to Prance."""
        mock_parser = MagicMock()
        mock_parser.specification = {"openapi": "3.0.3", "info": {"title": "Y", "version": "2"}}
        mock_parser_cls.return_value = mock_parser

        result = load_openapi("http://localhost:8080/spec.yaml")

        mock_parser_cls.assert_called_once_with("http://localhost:8080/spec.yaml")
        assert result["info"]["title"] == "Y"

    @patch("testpilot.openapi.loader.ResolvingParser")
    def test_url_returns_specification_dict(self, mock_parser_cls):
        """Loader must return parser.specification as a dict."""
        expected = {"openapi": "3.0.3", "info": {"title": "Z", "version": "3"}, "paths": {}}
        mock_parser = MagicMock()
        mock_parser.specification = expected
        mock_parser_cls.return_value = mock_parser

        result = load_openapi("https://api.example.com/openapi.json")

        assert result is expected


class TestLoaderErrors:
    def test_empty_source(self):
        with pytest.raises(LoaderError, match="must not be empty"):
            load_openapi("")

    def test_whitespace_source(self):
        with pytest.raises(LoaderError, match="must not be empty"):
            load_openapi("   ")

    def test_file_not_found(self):
        with pytest.raises(LoaderError, match="File not found"):
            load_openapi("/nonexistent/path/spec.json")

    def test_invalid_json(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        f.write("{not valid json!!!")
        f.close()
        try:
            with pytest.raises(LoaderError, match="Failed to load"):
                load_openapi(f.name)
        finally:
            os.unlink(f.name)

    def test_invalid_yaml(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.write(":\n  :\n    - ][invalid")
        f.close()
        try:
            with pytest.raises(LoaderError, match="Failed to load"):
                load_openapi(f.name)
        finally:
            os.unlink(f.name)

    def test_invalid_openapi_spec_missing_info(self):
        """Valid JSON but missing required OpenAPI fields → LoaderError."""
        path = _write_temp(INVALID_SPEC, ".json")
        try:
            with pytest.raises(LoaderError) as exc_info:
                load_openapi(path)
            # Exception chain must be preserved (raise LoaderError from exc)
            assert exc_info.value.__cause__ is not None
        finally:
            os.unlink(path)
