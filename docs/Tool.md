# Tool Calling

## Purpose

This document defines how tool calling should work in OmniCortex, what already exists in the codebase, what is missing, and the implementation order.

The goal is to support agent-controlled actions such as:

- calling external APIs
- triggering webhooks
- querying internal services
- dispatching button or flow payloads
- running structured business actions safely

Tool calling in this repo should be treated as a controlled execution layer on top of RAG and the existing LLM workflow, not as an unrestricted code execution feature.

For API-call tools specifically, the runtime payload should be a raw JSON body only. The backend should not require extra wrapper fields such as `body`, `payload`, or transport metadata in the tool call arguments.

## Current State

The codebase already contains the first pieces of tool support, but they are not wired end to end yet.

### Already present

1. LangGraph tool-capable agent flow exists in [`core/graph.py`](../core/graph.py).
   - `AgentGraph` supports `tools`
   - the LLM is bound with `self.llm.bind_tools(...)`
   - `ToolNode` and `tools_condition` are already imported and used

2. Tool prompt exists in [`core/prompts.py`](../core/prompts.py).
   - `TOOL_AGENT_PROMPT` already instructs the model to use tools carefully

3. Database model exists in [`core/database.py`](../core/database.py).
   - `Tool` model uses table `omni_tools`
   - fields: `id`, `name`, `type`, `content`, `agent_id`, `created_at`

4. API request/response DTOs exist in [`api.py`](../api.py).
   - `ToolCreate`
   - `ToolResponse`
   - `ToolDispatchRequest`

5. New runtime scaffold exists in [`tool/`](../tool).
   - `tool/adapters/base.py`
   - `tool/registry/registry.py`
   - `tool/schemas/tool_call.py`
   - `tool/tests/test_registry.py`

### Missing today

1. Tool REST endpoints are not implemented in `api.py`
   - README advertises them, but the route handlers do not exist

2. Database tools are not loaded into a runtime registry

3. Tool definitions stored in `omni_tools` are not translated into executable adapters

4. The main `/query` path still uses `process_question(...)` and does not yet switch to a tool-enabled graph

5. No validation or policy layer currently decides which tool types are safe for a given agent

## Design Principles

Tool calling should follow these rules:

- tools are explicit and registered, never inferred dynamically from arbitrary user text
- every tool has a typed input contract and a predictable JSON output
- every tool belongs to an agent
- every tool invocation is auditable
- dangerous actions require validation, allowlists, or dry-run support
- LLM decides when to call a tool, but the backend decides what is allowed

## Folder Structure

This is the intended structure under [`tool/`](../tool):

- `adapters/`
  - runtime executors for concrete tool types
- `schemas/`
  - request/result models and future validation schemas
- `registry/`
  - in-memory registration, lookup, and invocation
- `tests/`
  - tool-calling unit tests

Recommended future files:

- `tool/adapters/http_webhook.py`
- `tool/adapters/flow_dispatch.py`
- `tool/adapters/button_reply.py`
- `tool/adapters/crm_api.py`
- `tool/adapters/database_query.py`
- `tool/registry/loader.py`
- `tool/registry/factory.py`
- `tool/schemas/validators.py`

## Target Architecture

Tool calling should be implemented in four layers.

### 1. Persistence Layer

Source of truth is the `omni_tools` table in PostgreSQL.

Each record represents a backend-controlled tool definition:

```json
{
  "id": "uuid",
  "name": "create_lead",
  "type": "api_call",
  "agent_id": "agent-uuid",
  "content": {
    "url": "https://crm.example.com/leads",
    "method": "POST",
    "headers": {
      "Authorization": "Bearer ${secret}"
    },
    "timeout_sec": 10,
    "dry_run_supported": true
  }
}
```

### 2. Runtime Registry Layer

The backend loads stored tool definitions and converts them into registered adapters.

Current scaffold:

- `BaseToolAdapter` defines the execution contract
- `ToolRegistry` supports `register`, `get`, `list_tools`, and `invoke`

Required addition:

- a loader that reads `omni_tools` rows for an agent
- a factory that maps DB `type` to an adapter class

`api_call` should be the preferred type name for outbound HTTP tools. If legacy `webhook` rows already exist, they can be treated as an alias for the same adapter.

### 3. Execution Layer

Execution has two entry paths:

1. Direct backend dispatch
   - for admin test actions or API/webhook calls
   - invoked via `POST /tools/{tool_id}/dispatch`

2. LLM-driven invocation
   - used during `/query`
   - the active tools are bound into `AgentGraph`
   - the model emits tool calls
   - `ToolNode` executes them
   - the graph returns to the model with tool results

### 4. Audit Layer

Every invocation should emit:

- `request_id`
- `agent_id`
- `tool_id`
- `tool_name`
- `tool_type`
- input summary
- success/failure
- latency
- error message

This can first go to normal logs, and later to ClickHouse usage/event tables.

## How Query Flow Should Work

Today, normal chat uses `process_question(...)`.

Target flow:

1. user sends `/query`
2. backend resolves agent and conversation history
3. backend loads active tools for that agent from PostgreSQL
4. backend builds runtime adapters
5. backend creates a tool-enabled `AgentGraph`
6. RAG context is still retrieved first
7. graph runs with:
   - system prompt
   - conversation history
   - RAG context
   - registered tools
8. if the model requests a tool:
   - `ToolNode` executes it
   - result goes back into the graph
9. final answer is returned to the user

This keeps RAG and tool calling complementary:

- RAG answers from documents
- tools perform actions or live lookups

## API Plan

The repo already has DTOs for this, so implementation should match them.

### 1. List tools for an agent

`GET /agents/{agent_id}/tools`

Returns tools stored in `omni_tools` for that agent.

### 2. Create a tool for an agent

`POST /agents/{agent_id}/tools`

Request shape should align with `ToolCreate`:

```json
{
  "name": "create_lead",
  "type": "api_call",
  "content": {
    "url": "https://crm.example.com/leads",
    "method": "POST"
  },
  "agent_id": "agent-uuid"
}
```

### 3. Delete a tool

`DELETE /tools/{tool_id}`

Deletes the tool row after ownership check.

### 4. Dispatch a tool manually

`POST /tools/{tool_id}/dispatch`

Useful for testing and operational use.

For `api_call` tools, the request body should be the raw JSON body that will be forwarded to the target API.

Example:

```json
{
  "full_name": "Aman",
  "phone": "+911234567890",
  "source": "website"
}
```

The backend should resolve URL, method, headers, timeout, and auth from the tool definition stored in `content`. The dispatch request for `api_call` should not require wrapper fields such as:

- `body`
- `payload`
- `data`
- `headers`
- `url`

Those belong to tool configuration, not runtime input.

For non-HTTP tools, a separate typed dispatch schema can still exist if needed.

## Adapter Model

Each adapter should be a thin backend wrapper over a controlled action.

Base contract:

```python
class BaseToolAdapter(ABC):
    name: str
    description: str = ""

    @abstractmethod
    def invoke(self, arguments: dict) -> dict:
        ...
```

Recommended adapter categories:

- `api_call`
  - POST/PUT/PATCH external APIs using raw JSON body input
- `webhook`
  - legacy alias of `api_call`
- `flow`
  - dispatch structured flow payloads
- `button_reply`
  - emit reply options for messaging channels
- `schedule`
  - queue future actions
- `faq`
  - static structured answer tool
- `crm`
  - create/update/fetch CRM records

## Factory and Loader

Two backend pieces should be added.

### Factory

Maps DB row `type` to a concrete adapter.

Example:

```python
TOOL_TYPE_MAP = {
    "api_call": ApiCallToolAdapter,
    "webhook": ApiCallToolAdapter,
    "flow": FlowToolAdapter,
    "button_reply": ButtonReplyToolAdapter,
    "schedule": ScheduleToolAdapter,
}
```

## API-Call Tool Contract

This should be the contract for outbound HTTP tools.

### Stored tool definition

```json
{
  "name": "create_lead",
  "type": "api_call",
  "content": {
    "url": "https://crm.example.com/leads",
    "method": "POST",
    "headers": {
      "Authorization": "Bearer ${CRM_TOKEN}"
    },
    "timeout_sec": 10
  }
}
```

### Runtime tool input

```json
{
  "customer_name": "Aman",
  "email": "aman@example.com",
  "interest": "OmniCortex demo"
}
```

### Execution behavior

- backend sends the runtime JSON object as the HTTP request body unchanged
- backend does not expect a nested `body` field
- backend does not allow the model to override URL or headers at runtime
- backend may inject configured auth headers from env/config before sending

This keeps the model focused on business data only, while transport/security stays under backend control.

### Loader

Loads agent tools from DB and registers them:

```python
def build_registry_for_agent(agent_id: str) -> ToolRegistry:
    registry = ToolRegistry()
    rows = list_tools_for_agent(agent_id)
    for row in rows:
        adapter = build_adapter_from_row(row)
        registry.register(adapter)
    return registry
```

## Safety and Validation

This is the most important part of the design.

Rules:

- never allow arbitrary Python execution
- never allow unrestricted shell execution
- API-call domains should support allowlists
- secrets must come from env/config, not user prompt text
- validate input types before adapter execution
- enforce timeouts on all external calls
- support `dry_run` wherever possible
- redact secrets and sensitive payloads from logs

Minimum validation to add:

- tool `name` must be unique per agent
- tool `type` must be in an allowlist
- tool `content` must match the schema for that type
- `agent_id` in payload must match route param

## Implementation Plan

### Phase 1: Persistence API

Add tool CRUD endpoints in `api.py`.

Deliverables:

- `GET /agents/{agent_id}/tools`
- `POST /agents/{agent_id}/tools`
- `DELETE /tools/{tool_id}`
- ownership checks
- DB integration with `Tool` model

### Phase 2: Runtime Factory

Add runtime loader/factory under `tool/registry`.

Deliverables:

- `build_adapter_from_row(...)`
- `build_registry_for_agent(...)`
- adapter type allowlist

### Phase 3: First Real Adapters

Implement at least two concrete adapters.

Recommended first set:

1. `ApiCallToolAdapter`
2. `FaqToolAdapter`

These are easiest to validate and test.

### Phase 4: Manual Dispatch

Implement `POST /tools/{tool_id}/dispatch`.

Use cases:

- admin testing
- messaging integrations
- operational execution

### Phase 5: Query Integration

Replace or extend the current `/query` execution path so it can load agent tools and use `create_tool_agent(...)`.

Target:

- if no tools: existing RAG behavior
- if tools exist: tool-enabled graph behavior

### Phase 6: Observability

Add structured tool invocation logs and optional ClickHouse persistence.

### Phase 7: Test Coverage

Add tests for:

- CRUD endpoints
- adapter factory mapping
- registry load/invoke behavior
- invalid schema rejection
- agent ownership checks
- dry-run execution
- graph path with and without tools

## Recommended First Slice

The fastest safe implementation order is:

1. build CRUD endpoints
2. add `ApiCallToolAdapter`
3. add factory + loader
4. add manual dispatch endpoint
5. integrate tool-enabled graph into `/query`

This gives an end-to-end usable feature without overbuilding.

## Important Notes

There is a documentation mismatch today:

- [`README.md`](../README.md) advertises tool endpoints
- [`api.py`](../api.py) currently defines DTOs only, not the actual tool route handlers

This document should be treated as the implementation source of truth until those endpoints are added.

## Starter Example

Minimal flow for a first real tool:

1. create a DB tool row with type `api_call`
2. load that row into `ApiCallToolAdapter`
3. register it in `ToolRegistry`
4. expose it to `AgentGraph`
5. let the model call it when needed
6. return result into final answer

That is the path that should be implemented next.
