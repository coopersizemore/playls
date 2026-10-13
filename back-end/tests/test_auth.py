"""
Tests for the authentication system
"""

import os
from cryptography.fernet import Fernet

# Hermetic config: set before the app (and its load_dotenv calls) is imported.
# The engine is lazy, so no database connection is made by these tests.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-0123456789")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test_client_id")

import pytest
from fastapi.testclient import TestClient
from rest_api.app import app
from rest_api.services.auth_service import AuthService, SESSION_COOKIE

client = TestClient(app)

def test_login_endpoint():
    """Test the login endpoint returns auth URL and sets the state cookie"""
    response = client.get("/api/auth/login")
    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "spotify.com" in data["auth_url"]
    assert "spotify_oauth_state" in response.cookies

def test_callback_rejects_missing_state_cookie():
    """A callback without the matching state cookie must not log anyone in"""
    fresh_client = TestClient(app)
    response = fresh_client.get(
        "/api/auth/callback?code=abc&state=forged", follow_redirects=False
    )
    assert response.status_code in (302, 307)
    assert "error=auth_failed" in response.headers["location"]
    assert SESSION_COOKIE not in response.cookies

def test_callback_rejects_mismatched_state():
    fresh_client = TestClient(app)
    fresh_client.get("/api/auth/login")
    response = fresh_client.get(
        "/api/auth/callback?code=abc&state=forged", follow_redirects=False
    )
    assert "error=auth_failed" in response.headers["location"]

def test_auth_service_create_token():
    """Test JWT token creation"""
    token = AuthService.create_access_token({"sub": "123", "spotify_id": "test_user"})
    assert token is not None
    assert len(token) > 0

def test_protected_endpoint_without_auth():
    """Test that protected endpoints require authentication"""
    response = TestClient(app).get("/api/auth/me")
    assert response.status_code == 401

def test_bearer_header_is_not_accepted():
    """Auth is cookie-only now; a token in the Authorization header is ignored"""
    token = AuthService.create_access_token({"sub": "1"})
    response = TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

def test_invalid_session_cookie_rejected():
    c = TestClient(app, cookies={SESSION_COOKIE: "not-a-jwt"})
    assert c.get("/api/auth/me").status_code == 401

def test_state_changing_request_requires_csrf_header():
    c = TestClient(app, cookies={SESSION_COOKIE: "anything"})
    assert c.delete("/api/user/me").status_code == 403
    # With the header the CSRF check passes and the (bogus) session is rejected instead
    assert c.delete("/api/user/me", headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 401

def test_logout_clears_session_cookie():
    response = TestClient(app).post("/api/auth/logout")
    assert response.status_code == 200
    assert f'{SESSION_COOKIE}=""' in response.headers["set-cookie"]

@pytest.mark.parametrize("method,endpoint", [
    ("get", "/api/spotify/profile"),
    ("get", "/api/spotify/playlists"),
    ("get", "/api/spotify/recommendations"),
    ("get", "/api/spotify/search?q=test"),
    ("get", "/api/user/me/rotations"),
    ("delete", "/api/user/me"),
    ("get", "/api/rotation/1"),
    ("post", "/api/rotation/"),
    ("put", "/api/rotation/1"),
    ("delete", "/api/rotation/1"),
    ("get", "/api/rotation/1/songs"),
])
def test_endpoints_require_auth(method, endpoint):
    response = getattr(TestClient(app), method)(endpoint)
    assert response.status_code == 401, f"{method.upper()} {endpoint} should require auth"

def test_user_listing_is_gone():
    """The old unauthenticated user list leaked every user's Spotify tokens"""
    assert client.get("/api/user/").status_code in (404, 405)

def test_refresh_endpoint_is_gone():
    assert client.post("/api/auth/refresh").status_code in (404, 405)

def test_docs_disabled_by_default():
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404

def test_spotify_tokens_are_encrypted_at_rest():
    from rest_api.database.encryption import EncryptedText
    col = EncryptedText()
    stored = col.process_bind_param("spotify-access-token", None)
    assert stored != "spotify-access-token"
    assert "spotify-access-token" not in stored
    assert col.process_result_value(stored, None) == "spotify-access-token"
    assert col.process_bind_param(None, None) is None

if __name__ == "__main__":
    pytest.main([__file__])
