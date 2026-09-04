"""Dependency analysis and runtime-state management.

Phase 3D provides:
- Typed dependency models (DependencySource, DependencyTarget, ApiDependency)
- Conservative deterministic dependency inference (no LLM)
- Resource-family matching for endpoint grouping
- Run-scoped RuntimeState for capturing response values
- Secret-safe response scalar extraction
"""

from testpilot.dependency.analyzer import infer_dependencies
from testpilot.dependency.exceptions import DependencyError, ExtractionError
from testpilot.dependency.extractor import extract_scalar
from testpilot.dependency.models import (
    ApiDependency,
    DependencySource,
    DependencyTarget,
    ExtractedScalar,
)
from testpilot.dependency.resource_family import resource_family_from_path
from testpilot.dependency.runtime_state import RuntimeState, RuntimeValue

__all__ = [
    "ApiDependency",
    "DependencyError",
    "DependencySource",
    "DependencyTarget",
    "ExtractionError",
    "ExtractedScalar",
    "RuntimeState",
    "RuntimeValue",
    "extract_scalar",
    "infer_dependencies",
    "resource_family_from_path",
]
