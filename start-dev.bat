@echo off
echo Starting PlayLS Development Environment...

echo.
echo Starting Backend Server...
start "PlayLS Backend" cmd /k "cd back-end && .venv\Scripts\python -m rest_api.app"

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
echo This mode needs, in back-end/.env:
echo   FRONTEND_URL=http://127.0.0.1:3000
echo   SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/api/auth/callback (also in the Spotify dashboard)
echo Open http://127.0.0.1:3000, not localhost. "vercel dev" from the repo root is the simpler option.
echo.
pause
