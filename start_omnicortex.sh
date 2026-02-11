#!/bin/bash
# OmniCortex Startup Script
# Starts PostgreSQL and the API server

echo "🚀 Starting OmniCortex..."

# 1. Start PostgreSQL
echo "📊 Starting PostgreSQL..."
pg_ctl status -D local_pg_data > /dev/null 2>&1
if [ $? -ne 0 ]; then
    pg_ctl start -D local_pg_data -l storage/logs/postgresql.log
    echo "✅ PostgreSQL started"
    sleep 3
else
    echo "✅ PostgreSQL already running"
fi

# 2. Start Backend API
echo "🔧 Starting Backend API..."
python api.py &
API_PID=$!
echo "✅ Backend API started (PID: $API_PID)"

# 3. Start Frontend (optional)
echo "🎨 Starting Frontend..."
cd admin
npm run dev &
FRONTEND_PID=$!
echo "✅ Frontend started (PID: $FRONTEND_PID)"
cd ..

echo ""
echo "✅ OmniCortex is running!"
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for Ctrl+C
trap "echo ''; echo '🛑 Stopping services...'; kill $API_PID $FRONTEND_PID 2>/dev/null; pg_ctl stop -D local_pg_data; echo '✅ All services stopped'; exit 0" INT

# Keep script running
wait
