#!/bin/bash

echo "Starting PlayLS Development Environment..."

echo ""
echo "Starting Backend Server..."
cd back-end
.venv/bin/python -m rest_api.app &
BACKEND_PID=$!

echo ""
echo "Waiting for backend to start..."
sleep 3

echo ""
echo "Starting Frontend Server..."
cd ../playls_front_end
npm start &
FRONTEND_PID=$!

echo ""
echo "Development servers started!"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo ""
echo "This mode needs, in back-end/.env:"
echo "  FRONTEND_URL=http://127.0.0.1:3000"
echo "  SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/api/auth/callback (also in the Spotify dashboard)"
echo "Open http://127.0.0.1:3000, not localhost. 'vercel dev' from the repo root is the simpler option."
echo ""
echo "Press Ctrl+C to stop all servers"

# Function to cleanup on exit
cleanup() {
    echo "Stopping servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit
}

# Trap Ctrl+C
trap cleanup SIGINT

# Wait for user to stop
wait
