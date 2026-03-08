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

DROP TABLE IF EXISTS usage_logs;
DROP TABLE IF EXISTS chat_archive;
DROP TABLE IF EXISTS agent_logs;

CREATE TABLE usage_logs
(
    timestamp DateTime64(3) DEFAULT now64(3),
    request_id String DEFAULT '',
    session_id String DEFAULT '',
    id UUID,
    user_id Int32,
    product_id Int32 DEFAULT 0,
    channel_name LowCardinality(String) DEFAULT 'TEXT',      -- TEXT | VOICE
    channel_type LowCardinality(String) DEFAULT 'UTILITY',   -- UTILITY | MARKETING | AUTHENTICATION
    model LowCardinality(String) DEFAULT '',
    query_tokens UInt32 DEFAULT 0,
    prompt_tokens UInt32 DEFAULT 0,
    completion_tokens UInt32 DEFAULT 0,
    latency Float32 DEFAULT 0,
    hit_rate Int32 DEFAULT 0,
    cost Float32 DEFAULT 0,
    status LowCardinality(String) DEFAULT 'success',
    error String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (id, timestamp)
TTL timestamp + toIntervalDay(365)
SETTINGS index_granularity = 8192;

CREATE TABLE chat_archive
(
    timestamp DateTime64(3) DEFAULT now64(3),
    id UUID,
    user_id Int32,
    request_id String DEFAULT '',
    content String CODEC(ZSTD(3)),     -- JSON string: {"user":"...","ai":"..."}
    started_at DateTime64(3) DEFAULT now64(3),
    ended_at DateTime64(3) DEFAULT now64(3),
    session_id String DEFAULT '',
    status LowCardinality(String) DEFAULT 'success',
    error String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (id, timestamp)
TTL timestamp + toIntervalDay(365)
SETTINGS index_granularity = 8192;

CREATE TABLE agent_logs
(
    timestamp DateTime64(3) DEFAULT now64(3),
    event_id String DEFAULT '',
    id UUID,                                        -- Agent UUID
    user_id Int32,
    status LowCardinality(String) DEFAULT 'Active', -- Active | Updated | Deleted
    created_at DateTime64(3) DEFAULT now64(3),
    deleted_at Nullable(DateTime64(3)),
    agent_name String DEFAULT '',
    model_selection String DEFAULT '',
    role_type String DEFAULT '',
    subagent_type String DEFAULT '',
    vector_store String DEFAULT '',
    vector_chunks UInt32 DEFAULT 0,
    parent_chunks UInt32 DEFAULT 0,
    payload String DEFAULT '' CODEC(ZSTD(3)),
    error String DEFAULT ''
)
ENGINE = ReplacingMergeTree(timestamp)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (id, timestamp)
TTL timestamp + toIntervalDay(365)
SETTINGS index_granularity = 8192;
```

## 4) ALTER Existing Tables (if not dropping)

```sql
USE omnicortex;

ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS query_tokens UInt32 DEFAULT 0;
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS prompt_tokens UInt32 DEFAULT 0;
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS completion_tokens UInt32 DEFAULT 0;
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS status LowCardinality(String) DEFAULT 'success';
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS error String DEFAULT '';

ALTER TABLE chat_archive ADD COLUMN IF NOT EXISTS status LowCardinality(String) DEFAULT 'success';
ALTER TABLE chat_archive ADD COLUMN IF NOT EXISTS error String DEFAULT '';

ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS created_at DateTime64(3) DEFAULT now64(3);
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS deleted_at Nullable(DateTime64(3));
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS vector_store String DEFAULT '';
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS vector_chunks UInt32 DEFAULT 0;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS parent_chunks UInt32 DEFAULT 0;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS payload String DEFAULT '';
```

## 5) Verify Schema

```sql
USE omnicortex;
SHOW TABLES;
DESCRIBE TABLE usage_logs;
DESCRIBE TABLE chat_archive;
DESCRIBE TABLE agent_logs;
SHOW CREATE TABLE usage_logs;
SHOW CREATE TABLE chat_archive;
SHOW CREATE TABLE agent_logs;
```

## 6) Validation Queries

Latest usage:

```sql
SELECT
  timestamp,
  request_id,
  session_id,
  id,
  user_id,
  channel_name,
  channel_type,
  model,
  query_tokens,
  prompt_tokens,
  completion_tokens,
  latency,
  cost,
  status,
  error
FROM usage_logs
ORDER BY timestamp DESC
LIMIT 50;
```

Latest chats:

```sql
SELECT
  timestamp,
  request_id,
  session_id,
  id,
  status,
  error,
  JSONExtractString(content, 'user') AS user_text,
  JSONExtractString(content, 'ai') AS ai_text
FROM chat_archive
ORDER BY timestamp DESC
LIMIT 50;
```

Usage + chat join:

```sql
SELECT
  u.timestamp,
  u.request_id,
  u.session_id,
  u.id,
  u.model,
  u.query_tokens,
  u.prompt_tokens,
  u.completion_tokens,
  u.latency,
  u.cost,
  u.status AS usage_status,
  c.status AS chat_status,
  c.content
FROM usage_logs u
LEFT JOIN chat_archive c
  ON u.request_id = c.request_id
 AND u.session_id = c.session_id
 AND u.id = c.id
ORDER BY u.timestamp DESC
LIMIT 100;
```

Latest agent lifecycle:

```sql
SELECT
  timestamp,
  id,
  event_id,
  status,
  created_at,
  deleted_at,
  agent_name,
  model_selection,
  role_type,
  subagent_type,
  vector_store,
  vector_chunks,
  parent_chunks,
  error
FROM agent_logs
ORDER BY timestamp DESC
LIMIT 50;
```

Daily model analytics:

```sql
SELECT
  toDate(timestamp) AS day,
  model,
  channel_name,
  channel_type,
  count() AS requests,
  sum(query_tokens) AS total_query_tokens,
  sum(prompt_tokens) AS total_prompt_tokens,
  sum(completion_tokens) AS total_completion_tokens,
  round(avg(latency), 2) AS avg_latency,
  quantile(0.95)(latency) AS p95_latency,
  round(sum(cost), 6) AS total_cost
FROM usage_logs
GROUP BY day, model, channel_name, channel_type
ORDER BY day DESC, requests DESC;
```

## 7) Runtime Name Compatibility (Important)

Canonical tables used by runtime code:
1. `usage_logs`
2. `chat_archive`
3. `agent_logs`

If you have older tables, migrate/alias from:
1. `usage_log` -> `usage_logs`
2. `agent_events` / `agent_log` -> `agent_logs`

Also note:
1. `rag_query_tokens` has been removed from the ClickHouse writer payload.
2. if you had `industry` in `agent_logs`, migrate to `subagent_type`:
   `ALTER TABLE agent_logs RENAME COLUMN industry TO subagent_type;`

