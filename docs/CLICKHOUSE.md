# ClickHouse Setup Guide for Linux

This guide covers installing and configuring ClickHouse on Linux (Ubuntu/Debian).

## 1. Installation

### Option A: Quick Install (Recommended for Dev)
The easiest way to install the latest version.
```bash
curl https://clickhouse.com/ | sh
sudo ./clickhouse install
```

### Option B: RPM Install (Production)
For better package management integration.
```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://packages.clickhouse.com/rpm/clickhouse.repo
sudo yum install -y clickhouse-server clickhouse-client
```

## 2. Configuration

### Start the Server
```bash
sudo service clickhouse-server start
# OR
sudo systemctl start clickhouse-server
```

### Verify Status
```bash
sudo systemctl status clickhouse-server
```

### Enable Remote Access (Optional)
By default, ClickHouse listens only on localhost. To allow access from other services (e.g., your app container):
1. Edit config:
   ```bash
   sudo nano /etc/clickhouse-server/config.xml
   ```
2. Uncomment or add:
   ```xml
   <listen_host>0.0.0.0</listen_host>
   ```
3. Restart:
   ```bash
   sudo systemctl restart clickhouse-server
   ```

## 3. Usage Commands

### Connect via CLI
```bash
clickhouse-client
# Or if password set:
clickhouse-client --password
```

### Common SQL Commands
```sql
-- Create Database
CREATE DATABASE IF NOT EXISTS omnicortex;

-- Use Database
USE omnicortex;

-- 1. Usage Logs Table (High-performance analytics)
CREATE TABLE IF NOT EXISTS usage_logs (
    timestamp DateTime DEFAULT now(),
    agent_id String,
    user_id Int32,
    user_name String,
    product_id Int32,
    channel_name String,
    model String,
    prompt_tokens UInt32,
    completion_tokens UInt32,
    latency Float32,
    cost Float32
) ENGINE = MergeTree()
ORDER BY (agent_id, timestamp);

-- 2. Chat Archives (Long-term storage)
CREATE TABLE IF NOT EXISTS chat_archive (
    id UUID,
    timestamp DateTime DEFAULT now(),
    agent_id String,
    user_id Int32, 
    user_name String,
    product_id Int32,
    channel_name String,
    role String,
    content String,
    started_at DateTime DEFAULT now(),
    ended_at DateTime DEFAULT now(),
    session_id String
) ENGINE = MergeTree()
ORDER BY (agent_id, timestamp);

-- Show Created Tables
SHOW TABLES;

-- Check Table Data (Verify Mock Data)
SELECT count() FROM usage_logs;
SELECT * FROM usage_logs LIMIT 5;

SELECT count() FROM chat_archive;
SELECT * FROM chat_archive LIMIT 5;
```

## 4. Integration with OmniCortex
If you decide to re-enable the Memory Service:
1. Install driver: `uv add clickhouse-connect`
2. Update `.env`:
   ```ini
   CLICKHOUSE_HOST=localhost
   CLICKHOUSE_PORT=8123
   ```
