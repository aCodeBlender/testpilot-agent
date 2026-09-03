"""Unit tests for Intent Planner — T0302 + cleanup.

All LLM calls are mocked. No real API calls, no token consumption.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from testpilot.domain.spec import ApiEndpoint
from testpilot.planner.intent_exceptions import IntentPlannerError
from testpilot.planner.intent_planner import build_endpoint_catalog, plan_intent


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ep(id: str, method: str = "GET", path: str = "/x", summary: str = "", tags: list[str] | None = None) -> ApiEndpoint:
    return ApiEndpoint(id=id, method=method, path=path, summary=summary, tags=tags or [])


def _mock_llm_client(response_json: dict | str) -> MagicMock:
    """Create a mock LLM client that returns the given JSON."""
    client = MagicMock()
    if isinstance(response_json, dict):
        client.call.return_value = json.dumps(response_json)
    else:
        client.call.return_value = response_json
    return client


def _catalog() -> list[dict]:
    """Standard test catalog with 3 endpoints."""
    eps = [
        _ep("createUser", "POST", "/users", "Create user", ["user"]),
        _ep("listUsers", "GET", "/users", "List users", ["user"]),
        _ep("getUser", "GET", "/users/{id}", "Get user by ID", ["user"]),
    ]
    return build_endpoint_catalog(eps)


# ── build_endpoint_catalog ───────────────────────────────────────────────────


class TestBuildEndpointCatalog:
    def test_basic_format(self):
        eps = [_ep("a", "POST", "/a", "Summary A", ["tag1"])]
        catalog = build_endpoint_catalog(eps)
        assert len(catalog) == 1
        assert catalog[0]["id"] == "a"
        assert catalog[0]["method"] == "POST"
        assert catalog[0]["path"] == "/a"
        assert catalog[0]["summary"] == "Summary A"
        assert catalog[0]["tags"] == ["tag1"]

    def test_missing_summary(self):
        eps = [_ep("a", "GET", "/a")]
        catalog = build_endpoint_catalog(eps)
        assert catalog[0]["summary"] == ""
        assert catalog[0]["description"] == ""

    def test_empty_list(self):
        assert build_endpoint_catalog([]) == []


# ── plan_intent ──────────────────────────────────────────────────────────────


class TestPlanIntent:
    def test_select_all(self):
        client = _mock_llm_client({
            "selection_mode": "all",
            "selected_endpoint_ids": [],
            "excluded_methods": [],
            "focus_areas": [],
        })
        intent = plan_intent("test everything", _catalog(), client)
        assert intent.selection_mode == "all"

    def test_select_subset(self):
        client = _mock_llm_client({
            "selection_mode": "subset",
            "selected_endpoint_ids": ["createUser", "getUser"],
            "excluded_methods": [],
            "focus_areas": [],
        })
        intent = plan_intent("test create and get", _catalog(), client)
        assert intent.selection_mode == "subset"
        assert set(intent.selected_endpoint_ids) == {"createUser", "getUser"}

    def test_exclude_delete(self):
        client = _mock_llm_client({
            "selection_mode": "all",
            "selected_endpoint_ids": [],
            "excluded_methods": ["DELETE"],
            "focus_areas": [],
        })
        intent = plan_intent("no DELETE", _catalog(), client)
        assert "DELETE" in intent.excluded_methods

    def test_focus_areas_preserved(self):
        client = _mock_llm_client({
            "selection_mode": "all",
            "selected_endpoint_ids": [],
            "excluded_methods": [],
            "focus_areas": ["input validation"],
        })
        intent = plan_intent("focus on validation", _catalog(), client)
        assert intent.focus_areas == ["input validation"]

    def test_unknown_endpoint_id_rejected(self):
        client = _mock_llm_client({
            "selection_mode": "subset",
            "selected_endpoint_ids": ["createUser", "NONEXISTENT"],
            "excluded_methods": [],
            "focus_areas": [],
        })
        with pytest.raises(IntentPlannerError, match="NONEXISTENT"):
            plan_intent("test create", _catalog(), client)

    def test_duplicate_ids_deduped(self):
        client = _mock_llm_client({
            "selection_mode": "subset",
            "selected_endpoint_ids": ["createUser", "createUser", "getUser"],
            "excluded_methods": [],
            "focus_areas": [],
        })
        intent = plan_intent("test", _catalog(), client)
        assert intent.selected_endpoint_ids == ["createUser", "getUser"]

    def test_invalid_json_rejected(self):
        client = _mock_llm_client("not valid json {{{")
        with pytest.raises(IntentPlannerError, match="invalid JSON"):
            plan_intent("test", _catalog(), client)

    def test_invalid_schema_rejected(self):
        client = _mock_llm_client({"completely": "wrong"})
        with pytest.raises(IntentPlannerError, match="TestIntent schema"):
            plan_intent("test", _catalog(), client)

    def test_selection_mode_none(self):
        client = _mock_llm_client({
            "selection_mode": "none",
            "selected_endpoint_ids": [],
            "excluded_methods": [],
            "focus_areas": [],
        })
        intent = plan_intent("something unrelated", _catalog(), client)
        assert intent.selection_mode == "none"

    def test_all_with_ids_rejected_by_consistency(self):
        """LLM returns 'all' with IDs — rejected by TestIntent consistency."""
        client = _mock_llm_client({
            "selection_mode": "all",
            "selected_endpoint_ids": ["createUser"],
            "excluded_methods": [],
            "focus_areas": [],
        })
        with pytest.raises(IntentPlannerError, match="TestIntent schema"):
            plan_intent("test", _catalog(), client)

    def test_subset_with_empty_ids_rejected_by_consistency(self):
        """LLM returns 'subset' with empty IDs — rejected by TestIntent consistency."""
        client = _mock_llm_client({
            "selection_mode": "subset",
            "selected_endpoint_ids": [],
            "excluded_methods": [],
            "focus_areas": [],
        })
        with pytest.raises(IntentPlannerError, match="TestIntent schema"):
            plan_intent("test", _catalog(), client)

    def test_markdown_fences_stripped(self):
        raw_response = '```json\n{"selection_mode":"all","selected_endpoint_ids":[],"excluded_methods":[],"focus_areas":[]}\n```'
        client = MagicMock()
        client.call.return_value = raw_response
        intent = plan_intent("test", _catalog(), client)
        assert intent.selection_mode == "all"

    def test_empty_catalog_raises(self):
        client = _mock_llm_client({"selection_mode": "all"})
        with pytest.raises(IntentPlannerError, match="no endpoints"):
            plan_intent("test", [], client)

    def test_llm_call_failure_raises(self):
        client = MagicMock()
        client.call.side_effect = Exception("connection refused")
        with pytest.raises(IntentPlannerError, match="LLM call failed"):
            plan_intent("test", _catalog(), client)
