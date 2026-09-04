"""TestPilot Web UI — Gradio-based entry point.

This module provides a thin web interface over the existing Runner.
No execution logic is duplicated here.
"""

from __future__ import annotations

from testpilot.web.app import create_app

__all__ = ["create_app"]
