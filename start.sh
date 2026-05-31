#!/bin/bash
# Spustí Redis pokud neběží
if ! docker ps | grep -q redis; then
    echo "Starting Redis..."
    docker run -d --name redis-temp -p 6379:6379 redis:7-alpine
    sleep 2
fi

# Spustí backend
source venv/bin/activate
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 &

# Spustí frontend
cd frontend && npm run dev &

echo "All services started. Backend: http://localhost:8000, Frontend: http://localhost:5173"
