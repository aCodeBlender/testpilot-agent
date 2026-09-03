"""Tests for T0114: Endpoint Selector (tag filtering)."""

from testpilot.domain.spec import ApiEndpoint
from testpilot.openapi.selector import select_endpoints


# ── Helpers ─────────────────────────────────────────────────────────────────

def _ep(id: str, tags: list[str] | None = None) -> ApiEndpoint:
    return ApiEndpoint(id=id, path=f"/{id}", method="GET", tags=tags or [])


# ── Tests ───────────────────────────────────────────────────────────────────


class TestSelectEndpoints:
    def test_no_filters_returns_all(self):
        eps = [_ep("a"), _ep("b"), _ep("c")]
        result = select_endpoints(eps)
        assert len(result) == 3

    def test_include_tags(self):
        eps = [
            _ep("a", ["users"]),
            _ep("b", ["admin"]),
            _ep("c", ["users", "admin"]),
        ]
        result = select_endpoints(eps, include_tags=["users"])
        assert [e.id for e in result] == ["a", "c"]

    def test_include_tags_multiple(self):
        eps = [
            _ep("a", ["users"]),
            _ep("b", ["admin"]),
            _ep("c", ["public"]),
        ]
        result = select_endpoints(eps, include_tags=["users", "admin"])
        assert [e.id for e in result] == ["a", "b"]

    def test_exclude_tags(self):
        eps = [
            _ep("a", ["users"]),
            _ep("b", ["admin"]),
            _ep("c", ["users", "admin"]),
        ]
        result = select_endpoints(eps, exclude_tags=["admin"])
        assert [e.id for e in result] == ["a"]

    def test_include_and_exclude(self):
        """exclude is applied after include."""
        eps = [
            _ep("a", ["users"]),
            _ep("b", ["users", "internal"]),
            _ep("c", ["admin"]),
            _ep("d", ["users", "admin"]),
        ]
        result = select_endpoints(
            eps, include_tags=["users"], exclude_tags=["internal"]
        )
        assert [e.id for e in result] == ["a", "d"]

    def test_empty_include_means_all(self):
        eps = [_ep("a", ["x"]), _ep("b", ["y"])]
        result = select_endpoints(eps, include_tags=[])
        assert len(result) == 2

    def test_none_include_means_all(self):
        eps = [_ep("a", ["x"]), _ep("b", ["y"])]
        result = select_endpoints(eps, include_tags=None)
        assert len(result) == 2

    def test_empty_exclude_drops_none(self):
        eps = [_ep("a", ["x"])]
        result = select_endpoints(eps, exclude_tags=[])
        assert len(result) == 1

    def test_does_not_mutate_input(self):
        original = [_ep("a", ["users"]), _ep("b", ["admin"])]
        copy = list(original)
        select_endpoints(original, include_tags=["users"], exclude_tags=["admin"])
        assert len(original) == 2
        assert original[0].id == copy[0].id

    def test_empty_list(self):
        result = select_endpoints([], include_tags=["x"])
        assert result == []

    def test_no_tags_endpoint_excluded_by_include(self):
        """An endpoint with no tags must be excluded when include_tags is set."""
        eps = [_ep("a", []), _ep("b", ["users"])]
        result = select_endpoints(eps, include_tags=["users"])
        assert [e.id for e in result] == ["b"]

    def test_tag_order_preserved(self):
        eps = [_ep("z", ["x"]), _ep("a", ["x"]), _ep("m", ["x"])]
        result = select_endpoints(eps, include_tags=["x"])
        assert [e.id for e in result] == ["z", "a", "m"]
