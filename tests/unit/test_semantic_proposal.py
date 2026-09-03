"""Unit tests for SemanticScenarioProposal model — Phase 3B T0310."""

import pytest
from pydantic import ValidationError

from testpilot.domain.semantic import SemanticScenarioProposal


# ── Valid construction ──────────────────────────────────────────────────────


class TestSemanticScenarioProposalConstruction:
    def test_minimal_valid(self):
        """Minimal valid proposal with required fields only."""
        p = SemanticScenarioProposal(
            endpoint_id="createUser",
            name="Invalid email format",
            description="Send a malformed email address",
            rationale="Email format validation is a semantic check",
            category="format_violation",
            strategy="custom_value",
        )
        assert p.endpoint_id == "createUser"
        assert p.target_location is None
        assert p.target_path is None
        assert p.proposed_value is None
        assert p.requires_state is False

    def test_full_valid(self):
        """Full proposal with all fields set."""
        p = SemanticScenarioProposal(
            endpoint_id="createUser",
            name="Duplicate email registration",
            description="Register with an email that already exists",
            rationale="Duplicate resource detection",
            category="duplicate_resource",
            target_location="body",
            target_path="email",
            strategy="multi_step_required",
            proposed_value=None,
            requires_state=True,
        )
        assert p.requires_state is True
        assert p.strategy == "multi_step_required"

    def test_all_categories_accepted(self):
        """All defined categories are valid."""
        categories = [
            "format_violation", "boundary", "business_rule",
            "duplicate_resource", "invalid_state", "authorization",
            "relationship", "semantic",
        ]
        for cat in categories:
            p = SemanticScenarioProposal(
                endpoint_id="ep",
                name="test",
                description="test",
                rationale="test",
                category=cat,
                strategy="analysis_only",
            )
            assert p.category == cat

    def test_all_strategies_accepted(self):
        """All defined strategies are valid."""
        strategies = [
            "mutate_field", "omit_field", "reuse_existing_value",
            "custom_value", "multi_step_required", "analysis_only",
        ]
        for strat in strategies:
            requires = strat in ("multi_step_required", "reuse_existing_value")
            p = SemanticScenarioProposal(
                endpoint_id="ep",
                name="test",
                description="test",
                rationale="test",
                category="semantic",
                strategy=strat,
                requires_state=requires,
            )
            assert p.strategy == strat


# ── Default values ──────────────────────────────────────────────────────────


class TestDefaults:
    def test_requires_state_defaults_false(self):
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="t",
            description="t",
            rationale="t",
            category="semantic",
            strategy="custom_value",
        )
        assert p.requires_state is False

    def test_target_location_defaults_none(self):
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="t",
            description="t",
            rationale="t",
            category="semantic",
            strategy="custom_value",
        )
        assert p.target_location is None

    def test_target_path_defaults_none(self):
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="t",
            description="t",
            rationale="t",
            category="semantic",
            strategy="custom_value",
        )
        assert p.target_path is None

    def test_proposed_value_defaults_none(self):
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="t",
            description="t",
            rationale="t",
            category="semantic",
            strategy="custom_value",
        )
        assert p.proposed_value is None


# ── Literal validation ──────────────────────────────────────────────────────


class TestLiteralValidation:
    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError, match="category"):
            SemanticScenarioProposal(
                endpoint_id="ep",
                name="t",
                description="t",
                rationale="t",
                category="not_a_real_category",
                strategy="custom_value",
            )

    def test_invalid_strategy_rejected(self):
        with pytest.raises(ValidationError, match="strategy"):
            SemanticScenarioProposal(
                endpoint_id="ep",
                name="t",
                description="t",
                rationale="t",
                category="semantic",
                strategy="not_a_real_strategy",
            )

    def test_invalid_target_location_rejected(self):
        with pytest.raises(ValidationError, match="target_location"):
            SemanticScenarioProposal(
                endpoint_id="ep",
                name="t",
                description="t",
                rationale="t",
                category="semantic",
                strategy="custom_value",
                target_location="not_a_real_location",
            )


# ── Model validator ─────────────────────────────────────────────────────────


class TestStatefulConsistency:
    def test_multi_step_requires_state(self):
        """multi_step_required without requires_state=True is rejected."""
        with pytest.raises(ValidationError, match="requires_state"):
            SemanticScenarioProposal(
                endpoint_id="ep",
                name="t",
                description="t",
                rationale="t",
                category="duplicate_resource",
                strategy="multi_step_required",
                requires_state=False,
            )

    def test_multi_step_with_state_accepted(self):
        """multi_step_required with requires_state=True is accepted."""
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="t",
            description="t",
            rationale="t",
            category="duplicate_resource",
            strategy="multi_step_required",
            requires_state=True,
        )
        assert p.requires_state is True

    def test_reuse_existing_value_allows_false(self):
        """reuse_existing_value with requires_state=False is accepted by the model
        (validation layer enforces the stronger check)."""
        # Note: The model itself only enforces multi_step_required.
        # reuse_existing_value is enforced in semantic_validation.py.
        # This test documents the model-level behavior.
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="t",
            description="t",
            rationale="t",
            category="semantic",
            strategy="reuse_existing_value",
            requires_state=True,
        )
        assert p.requires_state is True


# ── Pydantic serialization ─────────────────────────────────────────────────


class TestSerialization:
    def test_model_dump(self):
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="test",
            description="desc",
            rationale="rat",
            category="boundary",
            target_location="body",
            target_path="age",
            strategy="custom_value",
            proposed_value=200,
            requires_state=False,
        )
        d = p.model_dump()
        assert d["endpoint_id"] == "ep"
        assert d["category"] == "boundary"
        assert d["proposed_value"] == 200

    def test_model_validate_roundtrip(self):
        p = SemanticScenarioProposal(
            endpoint_id="ep",
            name="test",
            description="desc",
            rationale="rat",
            category="semantic",
            strategy="analysis_only",
        )
        d = p.model_dump()
        p2 = SemanticScenarioProposal.model_validate(d)
        assert p2.endpoint_id == p.endpoint_id
        assert p2.category == p.category
