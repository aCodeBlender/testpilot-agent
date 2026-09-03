"""Tests for T0113: Domain Mapper (resolved dict → ApiSpec)."""

import pytest

from testpilot.openapi.mapper import map_to_api_spec
from testpilot.openapi.exceptions import MapperError


# ── Fixtures ────────────────────────────────────────────────────────────────

def _minimal(title="T", version="1.0", paths=None, servers=None):
    return {
        "openapi": "3.0.3",
        "info": {"title": title, "version": version},
        "servers": [{"url": u} for u in (servers or [])],
        "paths": paths or {},
    }


# ── Basic mapping ───────────────────────────────────────────────────────────

class TestMapperBasic:
    def test_minimal_spec(self):
        spec = map_to_api_spec(_minimal())
        assert spec.title == "T"
        assert spec.version == "1.0"
        assert spec.servers == []
        assert spec.endpoints == []

    def test_with_servers(self):
        spec = map_to_api_spec(_minimal(servers=["http://a.com", "http://b.com"]))
        assert spec.servers == ["http://a.com", "http://b.com"]

    def test_missing_title(self):
        raw = {"openapi": "3.0.3", "info": {"version": "1"}, "paths": {}}
        with pytest.raises(MapperError, match="info.title"):
            map_to_api_spec(raw)

    def test_missing_version(self):
        raw = {"openapi": "3.0.3", "info": {"title": "X"}, "paths": {}}
        with pytest.raises(MapperError, match="info.version"):
            map_to_api_spec(raw)

    def test_non_dict_input(self):
        with pytest.raises(MapperError, match="Expected dict"):
            map_to_api_spec("not a dict")


# ── Endpoint mapping ────────────────────────────────────────────────────────

class TestMapperEndpoints:
    def test_get_method(self):
        paths = {
            "/ping": {
                "get": {
                    "operationId": "ping",
                    "summary": "Ping",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        assert len(spec.endpoints) == 1
        ep = spec.endpoints[0]
        assert ep.method == "GET"
        assert ep.path == "/ping"
        assert ep.operation_id == "ping"
        assert ep.summary == "Ping"

    def test_post_method(self):
        paths = {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        assert ep.method == "POST"
        assert ep.request_body is not None
        assert ep.request_body.content_type == "application/json"
        assert ep.request_body.required is True
        assert "name" in ep.request_body.body_schema.properties

    def test_multiple_endpoints(self):
        paths = {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "operationId": "createUser",
                    "responses": {"201": {"description": "Created"}},
                },
            },
            "/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "responses": {"200": {"description": "OK"}},
                },
            },
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ids = [ep.id for ep in spec.endpoints]
        assert len(ids) == 3
        assert len(set(ids)) == 3  # all unique


# ── Parameters ──────────────────────────────────────────────────────────────

class TestMapperParameters:
    def test_operation_level_params(self):
        paths = {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "parameters": [
                        {
                            "name": "page",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 1},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        assert len(ep.parameters) == 1
        assert ep.parameters[0].name == "page"
        assert ep.parameters[0].location == "query"
        assert ep.parameters[0].param_schema.type == "integer"

    def test_path_level_params_merged(self):
        """Path-level parameters must appear in each operation."""
        paths = {
            "/users/{id}": {
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "get": {
                    "operationId": "getUser",
                    "responses": {"200": {"description": "OK"}},
                },
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        assert len(ep.parameters) == 1
        assert ep.parameters[0].name == "id"
        assert ep.parameters[0].location == "path"

    def test_operation_overrides_path_level_param(self):
        """Operation-level param with same (name, in) must override path-level."""
        paths = {
            "/users/{id}": {
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "X-Trace",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                ],
                "get": {
                    "operationId": "getUser",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},  # overridden to string
                        },
                        {
                            "name": "fields",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {"200": {"description": "OK"}},
                },
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        by_name = {p.name: p for p in ep.parameters}
        # id should be string (operation override), not integer (path-level).
        assert by_name["id"].param_schema.type == "string"
        # X-Trace inherited from path-level.
        assert by_name["X-Trace"].location == "header"
        # fields from operation-level.
        assert by_name["fields"].location == "query"


# ── operationId handling ────────────────────────────────────────────────────

class TestMapperOperationId:
    def test_missing_operation_id_generates_stable_id(self):
        paths = {
            "/health": {
                "get": {
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        assert ep.operation_id is None
        # Generated id should be stable and based on method + path.
        assert ep.id == "get_health"

    def test_missing_operation_id_with_path_params(self):
        paths = {
            "/users/{id}": {
                "get": {
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        assert ep.id == "get_users_id"

    def test_duplicate_operation_ids_get_deduplicated(self):
        """Two endpoints with the same operationId must get unique ids."""
        paths = {
            "/a": {
                "get": {
                    "operationId": "duplicate",
                    "responses": {"200": {"description": "OK"}},
                },
            },
            "/b": {
                "get": {
                    "operationId": "duplicate",
                    "responses": {"200": {"description": "OK"}},
                },
            },
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ids = [ep.id for ep in spec.endpoints]
        assert len(ids) == 2
        assert ids[0] == "duplicate"
        assert ids[1] == "duplicate_2"


# ── Responses ───────────────────────────────────────────────────────────────

class TestMapperResponses:
    def test_responses_keyed_by_status_code(self):
        paths = {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "responses": {
                        "201": {"description": "Created"},
                        "400": {"description": "Bad request"},
                        "5XX": {"description": "Server error"},
                    },
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        ep = spec.endpoints[0]
        assert set(ep.responses.keys()) == {"201", "400", "5XX"}
        assert ep.responses["201"].description == "Created"
        assert ep.responses["400"].description == "Bad request"

    def test_response_has_no_status_code_field(self):
        """ApiResponse must not carry a status_code field."""
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        resp = spec.endpoints[0].responses["200"]
        assert not hasattr(resp, "status_code")

    def test_response_json_content_preferred_over_other_types(self):
        """application/json must be preferred even when other types exist."""
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "text/plain": {"schema": {"type": "string"}},
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "integer"}},
                                    }
                                },
                            },
                        }
                    },
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        resp = spec.endpoints[0].responses["200"]
        assert resp.content_schema is not None
        assert resp.content_schema.type == "object"
        assert "id" in resp.content_schema.properties

    def test_response_empty_json_dict_not_treated_as_missing(self):
        """application/json={} (empty dict) must NOT fallback to other types."""
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {},
                                "text/plain": {"schema": {"type": "string"}},
                            },
                        }
                    },
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        resp = spec.endpoints[0].responses["200"]
        # Empty dict → no schema, but must NOT fallback to text/plain
        assert resp.content_schema is None

    def test_response_no_json_falls_back_to_first(self):
        """Without application/json, use the first available content type."""
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "text/plain": {"schema": {"type": "string"}},
                            },
                        }
                    },
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        resp = spec.endpoints[0].responses["200"]
        assert resp.content_schema is not None
        assert resp.content_schema.type == "string"

    def test_response_content_schema(self):
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        resp = spec.endpoints[0].responses["200"]
        assert resp.content_schema is not None
        assert resp.content_schema.type == "object"
        assert "id" in resp.content_schema.properties


# ── Schema mapping ──────────────────────────────────────────────────────────

class TestMapperSchema:
    def test_schema_constraints_mapped(self):
        """ApiSchema fields must be populated from resolved OpenAPI schema."""
        paths = {
            "/x": {
                "post": {
                    "operationId": "x",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 100,
                                            "pattern": "^[A-Za-z]+$",
                                        },
                                        "age": {
                                            "type": "integer",
                                            "minimum": 0,
                                            "maximum": 200,
                                        },
                                        "tags": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "minItems": 1,
                                            "maxItems": 10,
                                        },
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        body = spec.endpoints[0].request_body.body_schema
        assert body.required == ["name"]
        name_schema = body.properties["name"]
        assert name_schema.min_length == 1
        assert name_schema.max_length == 100
        assert name_schema.pattern == "^[A-Za-z]+$"
        age_schema = body.properties["age"]
        assert age_schema.minimum == 0
        assert age_schema.maximum == 200
        tags_schema = body.properties["tags"]
        assert tags_schema.type == "array"
        assert tags_schema.items.type == "string"
        assert tags_schema.min_items == 1

    def test_exclusive_minimum_and_maximum(self):
        """OpenAPI 3.0.x: exclusiveMinimum / exclusiveMaximum are booleans."""
        paths = {
            "/x": {
                "post": {
                    "operationId": "x",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "score": {
                                            "type": "number",
                                            "minimum": 0,
                                            "exclusiveMinimum": True,
                                            "maximum": 100,
                                            "exclusiveMaximum": True,
                                        },
                                        "age": {
                                            "type": "integer",
                                            "minimum": 0,
                                        },
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        body = spec.endpoints[0].request_body.body_schema
        score = body.properties["score"]
        assert score.minimum == 0
        assert score.exclusive_minimum is True
        assert score.maximum == 100
        assert score.exclusive_maximum is True
        # age: no exclusive flags → defaults to False
        age = body.properties["age"]
        assert age.minimum == 0
        assert age.exclusive_minimum is False
        assert age.exclusive_maximum is False

    def test_mapper_does_not_leak_raw_dict(self):
        """Domain model must not contain raw OpenAPI dict keys like '$ref'."""
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {"name": "q", "in": "query", "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"ok": {"type": "boolean"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        # Serialize to dict and check no raw OpenAPI keys leak through.
        data = spec.model_dump()
        import json
        dumped = json.dumps(data)
        assert "$ref" not in dumped
        assert "operationId" not in dumped  # should be operation_id in Pydantic
        assert "operation_id" in dumped


# ── RequestBody ─────────────────────────────────────────────────────────────

class TestMapperRequestBody:
    def test_json_body_preferred(self):
        paths = {
            "/x": {
                "post": {
                    "operationId": "x",
                    "requestBody": {
                        "content": {
                            "text/plain": {"schema": {"type": "string"}},
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                }
                            },
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        body = spec.endpoints[0].request_body
        assert body.content_type == "application/json"

    def test_no_json_falls_back_to_first(self):
        paths = {
            "/x": {
                "post": {
                    "operationId": "x",
                    "requestBody": {
                        "content": {
                            "text/plain": {"schema": {"type": "string"}},
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        body = spec.endpoints[0].request_body
        assert body.content_type == "text/plain"

    def test_no_request_body(self):
        paths = {
            "/x": {
                "get": {
                    "operationId": "x",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
        spec = map_to_api_spec(_minimal(paths=paths))
        assert spec.endpoints[0].request_body is None
