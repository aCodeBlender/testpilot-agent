"""Unit tests for TestIntent domain model — T0302 + cleanup."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from testpilot.domain.intent import TestIntent


class TestIntentModel:
    def test_valid_all_mode(self):
        intent = TestIntent(selection_mode="all")
        assert intent.selection_mode == "all"
        assert intent.selected_endpoint_ids == []
        assert intent.excluded_methods == []
        assert intent.focus_areas == []

    def test_valid_subset_mode(self):
        intent = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["createUser", "getUser"],
        )
        assert intent.selection_mode == "subset"
        assert intent.selected_endpoint_ids == ["createUser", "getUser"]

    def test_valid_none_mode(self):
        intent = TestIntent(selection_mode="none")
        assert intent.selection_mode == "none"
        assert intent.selected_endpoint_ids == []

    def test_excluded_methods_normalized(self):
        intent = TestIntent(
            selection_mode="all",
            excluded_methods=["delete", "patch"],
        )
        assert intent.excluded_methods == ["DELETE", "PATCH"]

    def test_invalid_excluded_method_rejected(self):
        with pytest.raises(ValidationError, match="Invalid HTTP method"):
            TestIntent(selection_mode="all", excluded_methods=["INVALID"])

    def test_duplicate_ids_deduped(self):
        intent = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["a", "b", "a", "c", "b"],
        )
        assert intent.selected_endpoint_ids == ["a", "b", "c"]

    def test_focus_areas_preserved(self):
        intent = TestIntent(
            selection_mode="all",
            focus_areas=["input validation", "error handling"],
        )
        assert intent.focus_areas == ["input validation", "error handling"]

    def test_invalid_selection_mode_rejected(self):
        with pytest.raises(ValidationError):
            TestIntent(selection_mode="invalid")

    def test_serialization_roundtrip(self):
        intent = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["a", "b"],
            excluded_methods=["DELETE"],
            focus_areas=["security"],
        )
        data = intent.model_dump()
        restored = TestIntent.model_validate(data)
        assert restored.selection_mode == intent.selection_mode
        assert restored.selected_endpoint_ids == intent.selected_endpoint_ids
        assert restored.excluded_methods == intent.excluded_methods

    # ── Consistency rules (Cleanup 4) ────────────────────────────────────

    def test_all_with_ids_rejected(self):
        """selection_mode='all' + non-empty selected_endpoint_ids → reject."""
        with pytest.raises(ValidationError, match="all.*but selected_endpoint_ids is non-empty"):
            TestIntent(selection_mode="all", selected_endpoint_ids=["a"])

    def test_subset_with_empty_ids_rejected(self):
        """selection_mode='subset' + empty selected_endpoint_ids → reject."""
        with pytest.raises(ValidationError, match="subset.*but selected_endpoint_ids is empty"):
            TestIntent(selection_mode="subset", selected_endpoint_ids=[])

    def test_subset_with_ids_accepted(self):
        intent = TestIntent(selection_mode="subset", selected_endpoint_ids=["a"])
        assert intent.selected_endpoint_ids == ["a"]

    def test_none_with_ids_rejected(self):
        """selection_mode='none' + non-empty selected_endpoint_ids → reject."""
        with pytest.raises(ValidationError, match="none.*but selected_endpoint_ids is non-empty"):
            TestIntent(selection_mode="none", selected_endpoint_ids=["a"])

    def test_none_without_ids_accepted(self):
        intent = TestIntent(selection_mode="none")
        assert intent.selected_endpoint_ids == []
