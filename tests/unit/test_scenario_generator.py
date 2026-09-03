"""Tests for T0201: Deterministic Scenario Generator."""

import pytest

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.schema import ApiSchema, ApiParameter, ApiRequestBody
from testpilot.planner.scenario_generator import generate_scenarios


# ── Helpers ──────────────────────────────────────────────────────────────────


def _endpoint(
    id: str = "ep-test",
    path: str = "/test",
    method: str = "GET",
    parameters: list[ApiParameter] | None = None,
    request_body: ApiRequestBody | None = None,
) -> ApiEndpoint:
    return ApiEndpoint(
        id=id,
        path=path,
        method=method,
        parameters=parameters or [],
        request_body=request_body,
    )


# ── happy_path ───────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_always_generated(self):
        ep = _endpoint()
        scenarios = generate_scenarios(ep)
        happy = [s for s in scenarios if s.category == "happy_path"]
        assert len(happy) == 1
        assert happy[0].target_location is None
        assert happy[0].target_path is None

    def test_happy_path_first(self):
        ep = _endpoint()
        scenarios = generate_scenarios(ep)
        assert scenarios[0].category == "happy_path"


# ── required_missing ─────────────────────────────────────────────────────────


class TestRequiredMissing:
    def test_required_query_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    required=True,
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        assert len(req) == 1
        assert req[0].target_location == "query"
        assert req[0].target_path == "page"

    def test_required_header_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="X-Request-Id",
                    location="header",
                    required=True,
                    param_schema=ApiSchema(type="string"),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        assert any(s.target_location == "header" and s.target_path == "X-Request-Id" for s in req)

    def test_optional_param_no_required_missing(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    required=False,
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        assert len(req) == 0

    def test_path_param_no_required_missing(self):
        """Path params are inherently required; invalid_path_id handles them."""
        ep = _endpoint(
            path="/users/{id}",
            parameters=[
                ApiParameter(
                    name="id",
                    location="path",
                    required=True,
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        assert len(req) == 0

    def test_required_body_field(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                required=True,
                body_schema=ApiSchema(
                    type="object",
                    required=["name"],
                    properties={
                        "name": ApiSchema(type="string"),
                        "email": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        assert len(req) == 1
        assert req[0].target_location == "body"
        assert req[0].target_path == "body.name"

    def test_optional_body_still_walks_schema_required(self):
        """requestBody.required=False but schema.required=['name'] → still generate required_missing."""
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                required=False,
                body_schema=ApiSchema(
                    type="object",
                    required=["name"],
                    properties={
                        "name": ApiSchema(type="string"),
                        "email": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        assert any(s.target_path == "body.name" for s in req)

    def test_nested_body_required(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                required=True,
                body_schema=ApiSchema(
                    type="object",
                    required=["profile"],
                    properties={
                        "profile": ApiSchema(
                            type="object",
                            required=["email"],
                            properties={
                                "email": ApiSchema(type="string"),
                                "name": ApiSchema(type="string"),
                            },
                        ),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        req = [s for s in scenarios if s.category == "required_missing"]
        paths = {s.target_path for s in req}
        assert "body.profile" in paths
        assert "body.profile.email" in paths


# ── null ─────────────────────────────────────────────────────────────────────


class TestNull:
    def test_non_nullable_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer", nullable=False),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        null = [s for s in scenarios if s.category == "null"]
        assert len(null) >= 1
        assert any(s.target_location == "query" and s.target_path == "page" for s in null)

    def test_nullable_field_no_null_scenario(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer", nullable=True),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        null = [s for s in scenarios if s.category == "null" and s.target_path == "page"]
        assert len(null) == 0

    def test_path_param_no_null_scenario(self):
        """Path params have no reliable HTTP null expression — no null scenario."""
        ep = _endpoint(
            path="/users/{id}",
            parameters=[
                ApiParameter(
                    name="id",
                    location="path",
                    param_schema=ApiSchema(type="integer", nullable=False),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        null = [s for s in scenarios if s.category == "null"]
        assert len(null) == 0

    def test_non_nullable_body_field(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string", nullable=False),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        null = [s for s in scenarios if s.category == "null"]
        assert any(s.target_location == "body" and s.target_path == "body.name" for s in null)


# ── wrong_type ───────────────────────────────────────────────────────────────


class TestWrongType:
    def test_typed_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        wt = [s for s in scenarios if s.category == "wrong_type"]
        assert len(wt) >= 1
        assert any(s.target_location == "query" and s.target_path == "page" for s in wt)

    def test_path_param_wrong_type(self):
        """Path params can have wrong_type scenarios."""
        ep = _endpoint(
            path="/users/{id}",
            parameters=[
                ApiParameter(
                    name="id",
                    location="path",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        scenarios = generate_scenarios(ep)
        wt = [s for s in scenarios if s.category == "wrong_type"]
        assert any(s.target_location == "path" and s.target_path == "id" for s in wt)

    def test_typed_body_field(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "age": ApiSchema(type="integer"),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        wt = [s for s in scenarios if s.category == "wrong_type"]
        assert any(s.target_location == "body" and s.target_path == "body.age" for s in wt)


# ── Nested body target_path ──────────────────────────────────────────────────


class TestNestedBodyPath:
    def test_dotted_path_for_nested(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "profile": ApiSchema(
                            type="object",
                            properties={
                                "email": ApiSchema(type="string"),
                            },
                        ),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        wt = [s for s in scenarios if s.category == "wrong_type" and s.target_path == "body.profile.email"]
        assert len(wt) == 1


# ── max_cases ────────────────────────────────────────────────────────────────


class TestMaxCases:
    def test_respects_max_cases(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name=f"p{i}", location="query", required=True, param_schema=ApiSchema(type="integer"))
                for i in range(10)
            ]
        )
        scenarios = generate_scenarios(ep, max_cases=5)
        assert len(scenarios) <= 5

    def test_happy_path_always_included(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name=f"p{i}", location="query", required=True, param_schema=ApiSchema(type="integer"))
                for i in range(10)
            ]
        )
        scenarios = generate_scenarios(ep, max_cases=3)
        happy = [s for s in scenarios if s.category == "happy_path"]
        assert len(happy) == 1

    def test_round_robin_interleave(self):
        """With enough categories and small max_cases, all categories should appear."""
        ep = _endpoint(
            method="POST",
            parameters=[
                ApiParameter(name="q", location="query", required=True, param_schema=ApiSchema(type="string")),
            ],
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    required=["name"],
                    properties={"name": ApiSchema(type="string", nullable=False)},
                ),
            ),
        )
        # 1 happy + required_missing(q) + required_missing(body.name) + null(body.name) + wrong_type(q) + wrong_type(body.name)
        scenarios = generate_scenarios(ep, max_cases=5)
        categories = {s.category for s in scenarios}
        assert "happy_path" in categories
        assert "required_missing" in categories
        assert "null" in categories
        assert "wrong_type" in categories


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_output(self):
        ep = _endpoint(
            method="POST",
            parameters=[
                ApiParameter(name="page", location="query", required=True, param_schema=ApiSchema(type="integer")),
            ],
            request_body=ApiRequestBody(
                required=True,
                body_schema=ApiSchema(
                    type="object",
                    required=["name"],
                    properties={"name": ApiSchema(type="string")},
                ),
            ),
        )
        run1 = [s.model_dump() for s in generate_scenarios(ep)]
        run2 = [s.model_dump() for s in generate_scenarios(ep)]
        assert run1 == run2


# ── readOnly exclusion ───────────────────────────────────────────────────────


class TestReadOnlyExclusion:
    """readOnly properties must not generate request-side mutation scenarios."""

    def test_readonly_required_no_required_missing(self):
        """readOnly required field should not produce required_missing scenario."""
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    required=["id", "name"],
                    properties={
                        "id": ApiSchema(type="integer", read_only=True),
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        rm = [s for s in scenarios if s.category == "required_missing"]
        # name should have required_missing, id should not
        assert any(s.target_path == "body.name" for s in rm)
        assert not any(s.target_path == "body.id" for s in rm)

    def test_readonly_no_null_scenario(self):
        """readOnly field should not produce null scenario."""
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "id": ApiSchema(type="integer", read_only=True, nullable=False),
                        "name": ApiSchema(type="string", nullable=False),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        null = [s for s in scenarios if s.category == "null"]
        assert not any(s.target_path == "body.id" for s in null)
        assert any(s.target_path == "body.name" for s in null)

    def test_readonly_no_wrong_type_scenario(self):
        """readOnly field should not produce wrong_type scenario."""
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "id": ApiSchema(type="integer", read_only=True),
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        wt = [s for s in scenarios if s.category == "wrong_type"]
        assert not any(s.target_path == "body.id" for s in wt)
        assert any(s.target_path == "body.name" for s in wt)

    def test_readonly_nested_no_scenarios(self):
        """readOnly nested property should not generate any mutation scenarios."""
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    required=["meta"],
                    properties={
                        "meta": ApiSchema(
                            type="object",
                            required=["id"],
                            properties={
                                "id": ApiSchema(type="integer", read_only=True),
                                "label": ApiSchema(type="string"),
                            },
                        ),
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        # meta.id is readOnly — should not appear in any mutation scenario
        assert not any(s.target_path and "meta.id" in s.target_path for s in scenarios)
        # meta.label is not readOnly — should appear
        assert any(s.target_path == "body.meta.label" for s in scenarios)

    def test_all_readonly_produces_only_happy(self):
        """If all body properties are readOnly, only happy_path should be generated."""
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    required=["id"],
                    properties={
                        "id": ApiSchema(type="integer", read_only=True),
                    },
                ),
            ),
        )
        scenarios = generate_scenarios(ep)
        assert len(scenarios) == 1
        assert scenarios[0].category == "happy_path"
