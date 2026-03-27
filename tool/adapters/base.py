from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseToolAdapter(ABC):
    """Base contract for all tool adapters."""

    name: str
    description: str = ""

    @abstractmethod
    def invoke(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool and return a JSON-serializable payload."""
        raise NotImplementedError

