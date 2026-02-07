#!/bin/bash
# ForgeFlow — Quick Start Script
# Usage: ./start.sh

set -e

echo "🔥 Starting ForgeFlow..."
echo ""

# Check for .env
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your API keys before running again."
    exit 1
fi

# Install backend dependencies
echo "📦 Installing backend dependencies..."
cd backend
pip install -r requirements.txt -q
cd ..

# Install frontend dependencies
echo "📦 Installing frontend dependencies..."
cd frontend
npm install --silent
cd ..

# Start backend and frontend in parallel
echo ""
echo "🚀 Starting services..."
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:3000"
echo "   API Docs: http://localhost:8000/docs"
echo ""

# Run backend (from project root so imports work)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Run frontend
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo "✅ ForgeFlow is running!"
echo "   Press Ctrl+C to stop."

# Handle shutdown
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo ''; echo '👋 ForgeFlow stopped.'" EXIT

wait
