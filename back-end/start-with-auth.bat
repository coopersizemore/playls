@echo off
echo Starting PlayLS Backend with Authentication Support
echo =====================================================

echo.
echo Checking if .env file exists...
if not exist .env (
    echo Creating .env file from template...
    copy env.example .env
    echo.
    echo IMPORTANT: Please edit .env file with your Spotify credentials!
    echo 1. Get your credentials from: https://developer.spotify.com/dashboard
    echo 2. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
    echo 3. Generate a secure SECRET_KEY for JWT tokens
    echo.
    pause
)

echo.
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Starting the server...
echo API will be available at: http://localhost:8000
echo API documentation at: http://localhost:8000/docs
echo Authentication demo: python auth_demo.py
echo.

python -m uvicorn rest_api.app:app --reload --host 0.0.0.0 --port 8000