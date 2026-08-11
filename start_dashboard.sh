#!/bin/bash

# Start Reddit Lead Finder

echo "Starting Reddit Lead Finder..."
echo ""

# Activate virtual environment
source .venv/bin/activate

# Check if database exists
if [ ! -f "data/threadscout.sqlite3" ]; then
    echo "No database found. Running initial scan..."
    python -m scripts.scan_once
fi

echo ""
echo "Starting FastAPI server..."
echo "Dashboard: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start the server
uvicorn app.main:app --host 127.0.0.1 --port 8000

