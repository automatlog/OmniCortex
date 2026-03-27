# Tool Calling

Tool-calling scaffold for OmniCortex.

Structure:
- `adapters/` : concrete tool adapters (HTTP, DB, CRM, webhook)
- `schemas/` : tool call request/response models
- `registry/` : registration, lookup, and invocation routing
- `tests/` : unit tests for tool-calling logic

Quick start:
1. Create a tool adapter by extending `BaseToolAdapter`.
2. Register it with `ToolRegistry.register(...)`.
3. Invoke with `ToolRegistry.invoke(tool_name, arguments)`.

Example:
```python
from tool.registry import ToolRegistry
from tool.adapters.base import BaseToolAdapter

class PingTool(BaseToolAdapter):
    name = "ping"
    description = "Simple health check tool"

    def invoke(self, arguments):
        return {"ok": True, "echo": arguments}

registry = ToolRegistry()
registry.register(PingTool())
print(registry.invoke("ping", {"message": "hello"}))
```
