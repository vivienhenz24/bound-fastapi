import asyncio
import urllib.parse

from sqlalchemy import select

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.models.user import User


def _run(coro):
    return asyncio.run(coro)


async def _get_user_by_email(async_session_maker, email: str) -> User | None:
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


async def _create_user(async_session_maker, email: str) -> User:
    async with async_session_maker() as session:
        user = User(
            email=email,
            hashed_password="hashed",
            first_name="Test",
            last_name="User",
            is_active=True,
            is_verified=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _set_google_settings():
    settings.google_client_id = "client-id"
    settings.google_client_secret = "client-secret"
    settings.google_redirect_uri = "http://localhost:8000/auth/google/callback"
    settings.frontend_url = "http://localhost:3000"


def test_google_callback_creates_user_and_redirects(client, async_session_maker, monkeypatch):
    _set_google_settings()

    async def fake_exchange(code: str, verifier: str):
        return {"access_token": "access-token"}

    async def fake_userinfo(token: str):
        return {
            "sub": "google-sub-1",
            "email": "google@example.com",
            "given_name": "Google",
            "family_name": "User",
        }

    monkeypatch.setattr(auth_routes, "_exchange_google_code", fake_exchange)
    monkeypatch.setattr(auth_routes, "_fetch_google_userinfo", fake_userinfo)

    client.cookies.set("google_oauth_state", "state")
    client.cookies.set("google_oauth_verifier", "verifier")
    client.cookies.set("google_oauth_redirect", "/home")

    response = client.get("/auth/google/callback?code=abc&state=state", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers.get("location")
    assert location is not None
    parsed = urllib.parse.urlparse(location)
    assert parsed.path == "/auth/google/callback"
    query = urllib.parse.parse_qs(parsed.query)
    assert "code" in query
    assert query.get("redirect") == ["/home"]

    user = _run(_get_user_by_email(async_session_maker, "google@example.com"))
    assert user is not None
    assert user.google_sub == "google-sub-1"
    assert user.is_verified is True


def test_google_callback_links_existing_user(client, async_session_maker, monkeypatch):
    _set_google_settings()
    existing = _run(_create_user(async_session_maker, "linked@example.com"))

    async def fake_exchange(code: str, verifier: str):
        return {"access_token": "access-token"}

    async def fake_userinfo(token: str):
        return {
            "sub": "google-sub-2",
            "email": "linked@example.com",
            "given_name": "Linked",
            "family_name": "User",
        }

    monkeypatch.setattr(auth_routes, "_exchange_google_code", fake_exchange)
    monkeypatch.setattr(auth_routes, "_fetch_google_userinfo", fake_userinfo)

    client.cookies.set("google_oauth_state", "state")
    client.cookies.set("google_oauth_verifier", "verifier")
    client.cookies.set("google_oauth_redirect", "/")

    response = client.get("/auth/google/callback?code=abc&state=state", follow_redirects=False)
    assert response.status_code == 302

    user = _run(_get_user_by_email(async_session_maker, "linked@example.com"))
    assert user is not None
    assert user.id == existing.id
    assert user.google_sub == "google-sub-2"
    assert user.is_verified is True


def test_google_complete_returns_tokens(client, async_session_maker):
    _set_google_settings()
    user = _run(_create_user(async_session_maker, "complete@example.com"))
    exchange_code = auth_routes._create_exchange_code(str(user.id))

    response = client.post("/auth/google/complete", json={"exchange_code": exchange_code})

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    set_cookie = response.headers.get("set-cookie")
    assert set_cookie and "refresh_token=" in set_cookie
