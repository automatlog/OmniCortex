from __future__ import annotations

import pytest

from tool.adapters.base import BaseToolAdapter
from tool.registry import ToolRegistry


class EchoTool(BaseToolAdapter):
    name = "echo"
    description = "Echo input payload"

    def invoke(self, arguments):
        return {"echo": arguments}


def test_register_and_invoke_tool():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.invoke("echo", {"message": "hello"})
    assert result == {"echo": {"message": "hello"}}


def test_register_duplicate_tool_fails():
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(ValueError):
        registry.register(EchoTool())


def test_get_missing_tool_fails():
    registry = ToolRegistry()

    with pytest.raises(KeyError):
        registry.get("missing")

