#!/bin/bash
set -e

echo "🐘 RESTARTING POSTGRESQL SETUP..."

# 1. Stop Service
echo "🛑 Stopping PostgreSQL..."
service postgresql stop || true

# 2. Start Service
echo "🟢 Starting PostgreSQL..."
service postgresql start

# 3. Reset Password (Aggressive)
echo "🔐 Resetting Password for 'postgres'..."
# We explicitly set it to 'postgredb'
su - postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgredb';\""

# 4. Re-create Database
echo "🗑️ Dropping old DB (if exists)..."
su - postgres -c "dropdb --if-exists omnicortex"
echo "✨ Creating new DB 'omnicortex'..."
su - postgres -c "createdb omnicortex"

# 5. Add Extensions
echo "🧩 Adding Extensions (vector)..."
su - postgres -c "psql -d omnicortex -c \"CREATE EXTENSION IF NOT EXISTS vector;\""

# 6. Verify Port
echo "🔍 Checking Port..."
netstat -tuln | grep 5432 || echo "⚠️ Port 5432 not visible yet?"

echo "✅ DATABASE RESET COMPLETE!"
