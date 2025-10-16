#!/bin/bash

echo "Starting PlayLS Development Environment..."

echo ""
echo "Starting Backend Server..."
cd back-end
python rest_api/app.py &
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
echo "Don't forget to:"
echo "1. Set up your Spotify app credentials in back-end/.env"
echo "2. Start ngrok for OAuth redirects: ngrok http 8000"
echo "3. Update your Spotify app redirect URI with the ngrok URL"
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
