# ClickHouse Setup (OmniCortex)

PostgreSQL remains source of truth for runtime state.  
ClickHouse is used for analytics and long-term logs.

## 1) Environment

Set in `.env`:

```ini
CLICKHOUSE_ENABLED=true
CLICKHOUSE_HOST=<clickhouse-host>
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=<clickhouse-user>
CLICKHOUSE_PASSWORD=<clickhouse-password>
CLICKHOUSE_DB=omnicortex
```

Optional buffering:

```ini
CLICKHOUSE_BATCH_SIZE=100
CLICKHOUSE_FLUSH_INTERVAL=1.5
CLICKHOUSE_MAX_BUFFER_ROWS=5000
```

## 2) Open ClickHouse shell

```bash
clickhouse-client --host <clickhouse-host> --port 9000 --user <clickhouse-user> --password
```

## 3) Create Canonical Tables

```sql
CREATE DATABASE IF NOT EXISTS omnicortex;
USE omnicortex;

DROP TABLE IF EXISTS omnicortex.UsageLogs;
DROP TABLE IF EXISTS omnicortex.ChatArchive;
DROP TABLE IF EXISTS omnicortex.AgentLogs;

CREATE TABLE omnicortex.UsageLogs
(
    Timestamp DateTime64(3) DEFAULT now64(3),
    RequestId String DEFAULT '',
    SessionId String DEFAULT '',
    Id UUID,
    UserId Int32,
    ProductId Int32 DEFAULT 0,                              -- auto-map: TEXT=6 (WhatsApp), VOICE=2
    ChannelName LowCardinality(String) DEFAULT 'TEXT',      -- TEXT | VOICE
    ChannelType LowCardinality(String) DEFAULT 'UTILITY',   -- TEXT: UTILITY|MARKETING|AUTHENTICATION, VOICE: PROMOTIONAL|TRANSACTIONAL
    Model LowCardinality(String) DEFAULT '',
    QueryTokens UInt32 DEFAULT 0,
    PromptTokens UInt32 DEFAULT 0,
    CompletionTokens UInt32 DEFAULT 0,
    Latency Float32 DEFAULT 0,
    HitRate Int32 DEFAULT 0,
    Cost Float32 DEFAULT 0,
    Status LowCardinality(String) DEFAULT 'success',
    Error String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(Timestamp)
ORDER BY (Id, Timestamp)
SETTINGS index_granularity = 8192;

CREATE TABLE omnicortex.ChatArchive
(
    Timestamp DateTime64(3) DEFAULT now64(3),
    Id UUID,
    UserId Int32,
    RequestId String DEFAULT '',
    Content String CODEC(ZSTD(3)),     -- JSON string: {"user":"...","ai":"..."}
    StartedAt DateTime64(3) DEFAULT now64(3),
    EndedAt DateTime64(3) DEFAULT now64(3),
    SessionId String DEFAULT '',
    Status LowCardinality(String) DEFAULT 'success',
    Error String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(Timestamp)
ORDER BY (Id, Timestamp)
SETTINGS index_granularity = 8192;

CREATE TABLE omnicortex.AgentLogs
(
    Timestamp DateTime64(3) DEFAULT now64(3),
    EventId String DEFAULT '',
    Id UUID,                                        -- Agent UUID
    UserId Int32,
    Status LowCardinality(String) DEFAULT 'Active', -- Active | Updated | Deleted
    CreatedAt DateTime64(3) DEFAULT now64(3),
    DeletedAt Nullable(DateTime64(3)),
    AgentName String DEFAULT '',
    ModelSelection String DEFAULT '',
    RoleType String DEFAULT '',
    SubagentType String DEFAULT '',
    VectorStore String DEFAULT '',
    VectorChunks UInt32 DEFAULT 0,
    ParentChunks UInt32 DEFAULT 0,
    Payload String DEFAULT '' CODEC(ZSTD(3)),
    Error String DEFAULT ''
)
ENGINE = ReplacingMergeTree(Timestamp)
PARTITION BY toYYYYMM(Timestamp)
ORDER BY (Id, Timestamp)
SETTINGS index_granularity = 8192;
```

## 4) ALTER Existing Tables (if not dropping)

```sql
USE omnicortex;

ALTER TABLE UsageLogs ADD COLUMN IF NOT EXISTS QueryTokens UInt32 DEFAULT 0;
ALTER TABLE UsageLogs ADD COLUMN IF NOT EXISTS PromptTokens UInt32 DEFAULT 0;
ALTER TABLE UsageLogs ADD COLUMN IF NOT EXISTS CompletionTokens UInt32 DEFAULT 0;
ALTER TABLE UsageLogs ADD COLUMN IF NOT EXISTS Status LowCardinality(String) DEFAULT 'success';
ALTER TABLE UsageLogs ADD COLUMN IF NOT EXISTS Error String DEFAULT '';

ALTER TABLE ChatArchive ADD COLUMN IF NOT EXISTS Status LowCardinality(String) DEFAULT 'success';
ALTER TABLE ChatArchive ADD COLUMN IF NOT EXISTS Error String DEFAULT '';

ALTER TABLE AgentLogs ADD COLUMN IF NOT EXISTS CreatedAt DateTime64(3) DEFAULT now64(3);
ALTER TABLE AgentLogs ADD COLUMN IF NOT EXISTS DeletedAt Nullable(DateTime64(3));
ALTER TABLE AgentLogs ADD COLUMN IF NOT EXISTS VectorStore String DEFAULT '';
ALTER TABLE AgentLogs ADD COLUMN IF NOT EXISTS VectorChunks UInt32 DEFAULT 0;
ALTER TABLE AgentLogs ADD COLUMN IF NOT EXISTS ParentChunks UInt32 DEFAULT 0;
ALTER TABLE AgentLogs ADD COLUMN IF NOT EXISTS Payload String DEFAULT '';

-- Make retention permanent (disable automatic row expiry)
ALTER TABLE UsageLogs REMOVE TTL;
ALTER TABLE ChatArchive REMOVE TTL;
ALTER TABLE AgentLogs REMOVE TTL;
```

## 5) Verify Schema

```sql
USE omnicortex;
SHOW TABLES;
DESCRIBE TABLE UsageLogs;
DESCRIBE TABLE ChatArchive;
DESCRIBE TABLE AgentLogs;
SHOW CREATE TABLE UsageLogs;
SHOW CREATE TABLE ChatArchive;
SHOW CREATE TABLE AgentLogs;
```

## 6) Validation Queries

Latest usage:

```sql
SELECT
  Timestamp,
  RequestId,
  SessionId,
  Id,
  UserId,
  ChannelName,
  ChannelType,
  Model,
  QueryTokens,
  PromptTokens,
  CompletionTokens,
  Latency,
  Cost,
  Status,
  Error
FROM UsageLogs
ORDER BY Timestamp DESC
LIMIT 50;
```

Latest chats:

```sql
SELECT
  Timestamp,
  RequestId,
  SessionId,
  Id,
  Status,
  Error,
  JSONExtractString(Content, 'user') AS UserText,
  JSONExtractString(Content, 'ai') AS AiText
FROM ChatArchive
ORDER BY Timestamp DESC
LIMIT 50;
```

Usage + chat join:

```sql
SELECT
  u.Timestamp,
  u.RequestId,
  u.SessionId,
  u.Id,
  u.Model,
  u.QueryTokens,
  u.PromptTokens,
  u.CompletionTokens,
  u.Latency,
  u.Cost,
  u.Status AS UsageStatus,
  c.Status AS ChatStatus,
  c.Content
FROM UsageLogs u
LEFT JOIN ChatArchive c
  ON u.RequestId = c.RequestId
 AND u.SessionId = c.SessionId
 AND u.Id = c.Id
ORDER BY u.Timestamp DESC
LIMIT 100;
```

Latest agent lifecycle:

```sql
SELECT
  Timestamp,
  Id,
  EventId,
  Status,
  CreatedAt,
  DeletedAt,
  AgentName,
  ModelSelection,
  RoleType,
  SubagentType,
  VectorStore,
  VectorChunks,
  ParentChunks,
  Error
FROM AgentLogs
ORDER BY Timestamp DESC
LIMIT 50;
```

Daily model analytics:

```sql
SELECT
  toDate(Timestamp) AS Day,
  Model,
  ChannelName,
  ChannelType,
  count() AS Requests,
  sum(QueryTokens) AS TotalQueryTokens,
  sum(PromptTokens) AS TotalPromptTokens,
  sum(CompletionTokens) AS TotalCompletionTokens,
  round(avg(Latency), 2) AS AvgLatency,
  quantile(0.95)(Latency) AS P95Latency,
  round(sum(Cost), 6) AS TotalCost
FROM UsageLogs
GROUP BY Day, Model, ChannelName, ChannelType
ORDER BY Day DESC, Requests DESC;
```

## 7) Runtime Name Compatibility (Important)

Canonical tables used by runtime code:
1. `UsageLogs`
2. `ChatArchive`
3. `AgentLogs`

If you have older tables, migrate/alias from:
1. `usage_log` / `usage_logs` -> `UsageLogs`
2. `chat_archive` -> `ChatArchive`
3. `agent_events` / `agent_log` / `agent_logs` -> `AgentLogs`

Also note:
1. `rag_query_tokens` has been removed from the ClickHouse writer payload.
2. if you had `industry` in `AgentLogs`, migrate to `SubagentType`:
   `ALTER TABLE AgentLogs RENAME COLUMN industry TO SubagentType;`

## 8) Insert Mock Data (3 Rows Each Table)

```bash
clickhouse-client --host <clickhouse-host> --port 9000 --user <clickhouse-user> --password --multiquery < scripts/clickhouse_mock_data.sql
```

This script inserts:
1. 3 rows into `omnicortex.UsageLogs`
2. 3 rows into `omnicortex.ChatArchive`
3. 3 rows into `omnicortex.AgentLogs`
