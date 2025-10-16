@echo off
echo Starting PlayLS Development Environment...

echo.
echo Starting Backend Server...
start "PlayLS Backend" cmd /k "cd back-end && python rest_api/app.py"

echo.
echo Waiting for backend to start...
timeout /t 3 /nobreak > nul

echo.
echo Starting Frontend Server...
start "PlayLS Frontend" cmd /k "cd playls_front_end && npm start"

echo.
echo Development servers started!
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Don't forget to:
echo 1. Set up your Spotify app credentials in back-end/.env
echo 2. Start ngrok for OAuth redirects: ngrok http 8000
echo 3. Update your Spotify app redirect URI with the ngrok URL
echo.
pause
