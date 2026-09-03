"""Report sub-package exceptions — T0206."""

from __future__ import annotations


class ReportError(Exception):
    """Raised on program / orchestration errors in report building."""
