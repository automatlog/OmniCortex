# PostgreSQL + pgvector Setup Guide

Complete guide for setting up PostgreSQL with `pgvector` for OmniCortex on Linux (Ubuntu/Debian).

---

## 1. Linux Installation (Ubuntu/Debian)

```bash
# Update package list
sudo apt update

# Install PostgreSQL 16
sudo apt install postgresql postgresql-contrib -y

# Install pgvector extension
sudo apt install postgresql-16-pgvector -y

# Start and enable PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

---

## 2. Cloud Deployment Setup

### PostgreSQL Cloud Options

You can use any managed PostgreSQL service that supports pgvector extension (version 15+):
- RunPod (with PostgreSQL in container)
- DigitalOcean Managed Databases
- Supabase
- Neon
- Railway

### Self-Hosted on RunPod

Recommended for RunPod deployments. Install PostgreSQL directly on your pod.

1.  **Install PostgreSQL**:
    ```bash
    apt update
    apt install -y postgresql postgresql-contrib postgresql-16-pgvector
    ```

2.  **Enable Extension**:
    ```bash
    sudo -u postgres psql -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
    ```

**Ubuntu/Debian:**
```bash
# Install Postgres 16
sudo apt update
sudo apt install -y postgresql postgresql-contrib postgresql-16-pgvector

# Init & Start
sudo postgresql-setup --initdb
sudo systemctl enable postgresql --now

# Build pgvector
cd /tmp
git clone --branch v0.6.0 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

---

## 3. Enable Extension & Create Database
Once installed (Local or Cloud), run these SQL commands:

```sql
-- Connect
psql -h <HOST> -U <USER> postgres

-- 1. Create User & DB
CREATE USER omni WITH PASSWORD 'secure_password';
CREATE DATABASE omnicortex;
GRANT ALL PRIVILEGES ON DATABASE omnicortex TO omni;

-- 2. Connect to DB
\c omnicortex

-- 3. Enable Vector Extension (CRITICAL)
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify
\dx
-- Should output: vector | ... | vector data type ...
```

---

## 4. Configuration (.env)

Update your `.env` file with the connection string:

```ini
# Format: postgresql://[user]:[password]@[host]:[port]/[database]

# Local / RunPod
DATABASE_URL=postgresql://postgres:password@localhost:5432/omnicortex

# Cloud Managed (DigitalOcean, Supabase, etc.)
DATABASE_URL=postgresql://user:password@host.example.com:5432/omnicortex
DATABASE_URL=postgresql://postgres:password@localhost:5432/omnicortex
```

---

## 5. OmniCortex Schema
The app automatically creates these tables on first run:
-   `omni_agents`: Agent metadata
-   `omni_messages`: Chat history
-   `omni_documents`: Document metadata
-   `langchain_pg_embedding`: Vector embeddings (managed by LangChain)

---

## 6. Troubleshooting

**"extension vector does not exist"**
-   You haven't installed the `pgvector` package. Install with: `apt install postgresql-16-pgvector`

**"password authentication failed"**
-   Verify username/password in your `.env` file

**"timeout / connection refused"**
-   Check Firewall / Security Groups.
-   **RunPod**: Ensure PostgreSQL is running (`systemctl status postgresql`)
-   **Cloud**: Check firewall rules and allow your IP address
