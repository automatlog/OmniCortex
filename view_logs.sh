#!/bin/bash
# OmniCortex Log Viewer
# Shows real-time logs from all services

echo "📊 OmniCortex Log Viewer"
echo "========================"
echo ""
echo "Choose what to view:"
echo "1) Backend API logs (Python)"
echo "2) PostgreSQL logs"
echo "3) All logs (combined)"
echo "4) Live tail (follow mode)"
echo ""
read -p "Enter choice (1-4): " choice

case $choice in
    1)
        echo "📋 Backend API Logs:"
        echo "===================="
        # Show Python API logs from terminal output
        echo "Tip: Run 'python api.py' in a separate terminal to see live logs"
        ;;
    2)
        echo "📋 PostgreSQL Logs:"
        echo "===================="
        if [ -f storage/logs/postgresql.log ]; then
            tail -50 storage/logs/postgresql.log
        else
            echo "No PostgreSQL logs found"
        fi
        ;;
    3)
        echo "📋 All Logs:"
        echo "===================="
        echo ""
        echo "PostgreSQL:"
        if [ -f storage/logs/postgresql.log ]; then
            tail -20 storage/logs/postgresql.log
        fi
        echo ""
        ;;
    4)
        echo "📋 Live Tail Mode (Ctrl+C to exit):"
        echo "===================================="
        if [ -f storage/logs/postgresql.log ]; then
            tail -f storage/logs/postgresql.log
        else
            echo "No logs to tail"
        fi
        ;;
    *)
        echo "Invalid choice"
        ;;
esac
