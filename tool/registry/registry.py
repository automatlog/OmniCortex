from __future__ import annotations

from typing import Any, Dict, List

from tool.adapters.base import BaseToolAdapter


class ToolRegistry:
    """Simple in-memory registry for tool adapters."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseToolAdapter] = {}

    def register(self, adapter: BaseToolAdapter) -> None:
        name = str(getattr(adapter, "name", "") or "").strip()
        if not name:
            raise ValueError("Tool adapter must define a non-empty 'name'.")
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = adapter

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseToolAdapter:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered.")
        return self._tools[name]

    def list_tools(self) -> List[str]:
        return sorted(self._tools.keys())

    def invoke(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        adapter = self.get(name)
        return adapter.invoke(arguments or {})

