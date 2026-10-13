@echo off
echo Starting PlayLS Development Environment...

echo.
echo Starting Backend Server...
start "PlayLS Backend" cmd /k "cd back-end && python -m rest_api.app"

echo.
echo Backend started!
echo http://localhost:8000

