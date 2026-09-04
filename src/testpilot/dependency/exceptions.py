"""Dependency analysis and runtime-state exception types."""

from __future__ import annotations


class DependencyError(Exception):
    """Base for all dependency/runtime-state errors."""


class ExtractionError(DependencyError):
    """Failed to extract a scalar from a response."""
