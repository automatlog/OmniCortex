#!/bin/bash
# Reset Postgres Password and Create Database
# Run as root

echo "🔧 Resetting Postgres Password..."

# Start Postgres if not running
service postgresql start

# Reset password for 'postgres' user to match .env (postgresdb)
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgresdb';"

# Create database if it doesn't exist
sudo -u postgres psql -c "CREATE DATABASE omnicortex;" || echo "Database omnicortex already exists"

# Verify connection
echo "🔍 Verifying connection..."
export PGPASSWORD=postgresdb
psql -h localhost -U postgres -d omnicortex -c "SELECT 1;"

if [ $? -eq 0 ]; then
    echo "✅ Database connection successful!"
else
    echo "❌ Database connection failed."
fi
