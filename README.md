# PlayLS - Lazy Susan for Playlists

Keep your Spotify playlists fresh by rotating songs in and out on a regular schedule.

## Overview

PlayLS helps users maintain fresh playlists by:
- Tracking when songs were added to playlists
- Prompting users to review songs after a set time interval
- Allowing users to keep or remove songs with a simple swipe interface
- Providing recommendations for new songs to replace removed ones

## Tech Stack

- **Frontend**: React with Material-UI
- **Backend**: FastAPI (Python)
- **Music API**: Spotify Web API
- **Development**: ngrok for local OAuth redirects

## Setup Instructions

### Prerequisites

1. **Spotify Developer Account**
   - Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   - Create a new app
   - Note your Client ID and Client Secret
   - Set redirect URI to `http://localhost:8000/auth/callback` (for local development)

2. **Python 3.8+**
3. **Node.js 16+**
4. **ngrok** (for local development)

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd back-end
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create environment file:
   ```bash
   cp env.example .env
   ```

5. Edit `.env` file with your Spotify credentials:
   ```
   SPOTIFY_CLIENT_ID=your_spotify_client_id_here
   SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
   REDIRECT_URI=http://localhost:8000/auth/callback
   ```

6. Start the backend server:
   ```bash
   python rest_api/app.py
   ```

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd playls_front_end
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm start
   ```

### ngrok Setup (for local development)

1. Install ngrok:
   ```bash
   npm install -g ngrok
   # or download from https://ngrok.com/download
   ```

2. Start ngrok tunnel:
   ```bash
   ngrok http 8000
   ```

3. Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)

4. Update your Spotify app's redirect URI in the Spotify Developer Dashboard to:
   ```
   https://your-ngrok-url.ngrok.io/auth/callback
   ```

5. Update your backend `.env` file:
   ```
   REDIRECT_URI=https://your-ngrok-url.ngrok.io/auth/callback
   ```

## Usage

1. Start both backend and frontend servers
2. Open http://localhost:3000 in your browser
3. Click "Login with Spotify" to authenticate
4. Create a rotation from one of your playlists
5. Review songs and keep or remove them
6. Find new songs to replace removed ones

## Features

### Core Features
- ✅ Spotify OAuth login
- ✅ Connect/create Spotify playlists
- ✅ Set rotation intervals (7-90 days)
- ✅ Song review interface with keep/remove actions
- ✅ Song recommendations based on various criteria
- ✅ Rotation history tracking

### Nice-to-Have Features (Future)
- Skip detection and automatic removal suggestions
- Statistics (most skipped songs, longest kept songs)
- Social features and collaborative rotations
- Mobile app

## API Endpoints

### Authentication
- `GET /auth/login` - Initiate Spotify OAuth
- `GET /auth/callback` - Handle OAuth callback

### User Data
- `GET /user/playlists` - Get user's playlists
- `GET /playlist/{playlist_id}/tracks` - Get playlist tracks

### Rotations
- `POST /rotation/create` - Create new rotation
- `GET /rotation/{rotation_id}/review` - Get songs to review
- `POST /rotation/{rotation_id}/review` - Review a song (keep/remove)

### Recommendations
- `GET /recommendations` - Get song recommendations

## Development

### Project Structure
```
playls/
├── back-end/
│   ├── rest_api/
│   │   └── app.py          # FastAPI application
│   ├── requirements.txt    # Python dependencies
│   └── env.example        # Environment variables template
├── playls_front_end/      # React application
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── contexts/      # React contexts
│   │   └── App.js         # Main app component
│   └── package.json       # Node.js dependencies
└── README.md
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see LICENSE file for details