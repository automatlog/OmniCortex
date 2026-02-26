# ClickHouse Setup (OmniCortex)

PostgreSQL remains source of truth for runtime app state.  
ClickHouse is used for analytics and chat/usage history.

## 1) Environment

Set in `.env`:

```ini
CLICKHOUSE_ENABLED=true
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
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
clickhouse-client --host localhost --port 9000 --user default --password
```

## 3) Drop and recreate tables (recommended now)

```sql
CREATE DATABASE IF NOT EXISTS omnicortex;
USE omnicortex;

DROP TABLE IF EXISTS usage_logs;
DROP TABLE IF EXISTS chat_archive;

CREATE TABLE usage_logs (
    timestamp DateTime DEFAULT now(),
    request_id String DEFAULT '',
    session_id String DEFAULT '',
    id UUID,
    user_id Int32,
    product_id Int32,
    channel_name String,         -- TEXT | VOICE
    channel_type String,         -- UTILITY | MARKETING | AUTHENTICATION
    model String,
    question_tokens UInt32 DEFAULT 0,      -- original user question
    rag_query_tokens UInt32 DEFAULT 0,     -- masked/normalized query sent to retrieval
    prompt_tokens UInt32 DEFAULT 0,        -- prompt tokens sent to LLM
    completion_tokens UInt32 DEFAULT 0,    -- generated tokens from LLM
    latency Float32 DEFAULT 0,
    hit_rate Int32 DEFAULT 0,
    cost Float32 DEFAULT 0,
    status String DEFAULT 'success',
    error String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (id, timestamp);

CREATE TABLE chat_archive (
    timestamp DateTime DEFAULT now(),
    id UUID,
    user_id Int32,
    request_id String DEFAULT '',
    content String,               -- JSON string: {"user":"...","ai":"..."}
    started_at DateTime DEFAULT now(),
    ended_at DateTime DEFAULT now(),
    session_id String DEFAULT '',
    status String DEFAULT 'success',
    error String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (id, timestamp);
```

## 4) If you keep existing tables, add missing columns

```sql
USE omnicortex;

ALTER TABLE usage_logs
    ADD COLUMN IF NOT EXISTS question_tokens UInt32 DEFAULT 0;

ALTER TABLE usage_logs
    ADD COLUMN IF NOT EXISTS rag_query_tokens UInt32 DEFAULT 0;

ALTER TABLE usage_logs
    ADD COLUMN IF NOT EXISTS prompt_tokens UInt32 DEFAULT 0;

ALTER TABLE usage_logs
    ADD COLUMN IF NOT EXISTS completion_tokens UInt32 DEFAULT 0;
```

If old columns exist and are no longer needed:

```sql
ALTER TABLE usage_logs DROP COLUMN IF EXISTS query_tokens;
ALTER TABLE usage_logs DROP COLUMN IF EXISTS response_tokens;
```

## 5) Verify schema

```sql
USE omnicortex;
SHOW TABLES;
DESCRIBE TABLE usage_logs;
DESCRIBE TABLE chat_archive;
SHOW CREATE TABLE usage_logs;
SHOW CREATE TABLE chat_archive;
```

## 6) Quick validation queries

Latest usage:

```sql
SELECT
  timestamp,
  request_id,
  session_id,
  id,
  channel_name,
  channel_type,
  model,
  question_tokens,
  rag_query_tokens,
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

Usage + chat join (debug by turn):

```sql
SELECT
  u.timestamp,
  u.request_id,
  u.session_id,
  u.id,
  u.model,
  u.question_tokens,
  u.rag_query_tokens,
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

Daily model analytics:

```sql
SELECT
  toDate(timestamp) AS day,
  model,
  channel_name,
  channel_type,
  count() AS requests,
  sum(question_tokens) AS total_question_tokens,
  sum(rag_query_tokens) AS total_rag_query_tokens,
  sum(prompt_tokens) AS total_prompt_tokens,
  sum(completion_tokens) AS total_completion_tokens,
  round(avg(latency), 2) AS avg_latency,
  quantile(0.95)(latency) AS p95_latency,
  round(sum(cost), 6) AS total_cost
FROM usage_logs
GROUP BY day, model, channel_name, channel_type
ORDER BY day DESC, requests DESC;
```
