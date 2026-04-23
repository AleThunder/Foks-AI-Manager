from __future__ import annotations

from typing import Any, Protocol


class ProductPatchGeneratorPort(Protocol):
    """Describe the AI gateway used to generate normalized product patch drafts."""

    def generate_patch(self, *, context: dict[str, Any], instructions: str) -> dict[str, Any]:
        """Generate a normalized draft patch payload from stable product context."""
