import asyncio
from uuid import UUID

from sqlalchemy import select

from app.models.refresh_token import RefreshToken
from app.models.user import User


def _run(coro):
    return asyncio.run(coro)


async def _get_user_by_email(async_session_maker, email: str) -> User | None:
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


async def _get_refresh_tokens(async_session_maker, user_id: UUID) -> list[RefreshToken]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        return list(result.scalars().all())


async def _set_user_active(async_session_maker, user_id: UUID, active: bool) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.is_active = active
        await session.commit()


def _register_user(client, email="test@example.com", password="password123"):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
        },
    )


def _login_user(client, email="test@example.com", password="password123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_and_login_and_me(client, async_session_maker):
    register_response = _register_user(client)
    assert register_response.status_code == 201

    login_response = _login_user(client)
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    me_response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_response.status_code == 200
    data = me_response.json()
    assert data["email"] == "test@example.com"
    assert data["is_active"] is True

    user = _run(_get_user_by_email(async_session_maker, "test@example.com"))
    assert user is not None


def test_register_duplicate_fails(client):
    _register_user(client, email="duplicate@example.com")
    duplicate_response = _register_user(client, email="duplicate@example.com")
    assert duplicate_response.status_code == 400


def test_login_invalid_password(client):
    _register_user(client, email="badpass@example.com", password="password123")
    response = _login_user(client, email="badpass@example.com", password="wrongpass")
    assert response.status_code == 401


def test_me_requires_auth(client):
    response = client.get("/auth/me")
    assert response.status_code == 403 or response.status_code == 401


def test_refresh_token_rotation(client, async_session_maker):
    _register_user(client, email="refresh@example.com")
    login_response = _login_user(client, email="refresh@example.com")
    assert login_response.status_code == 200

    refresh_response = client.post("/auth/refresh")
    assert refresh_response.status_code == 200
    assert "access_token" in refresh_response.json()

    user = _run(_get_user_by_email(async_session_maker, "refresh@example.com"))
    tokens = _run(_get_refresh_tokens(async_session_maker, user.id))
    assert len(tokens) >= 2
    assert any(token.revoked for token in tokens)


def test_refresh_requires_cookie(client):
    response = client.post("/auth/refresh")
    assert response.status_code == 401


def test_logout_revokes_and_clears_cookie(client, async_session_maker):
    _register_user(client, email="logout@example.com")
    login_response = _login_user(client, email="logout@example.com")
    access_token = login_response.json()["access_token"]

    logout_response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_response.status_code == 200

    refresh_response = client.post("/auth/refresh")
    assert refresh_response.status_code == 401

    user = _run(_get_user_by_email(async_session_maker, "logout@example.com"))
    tokens = _run(_get_refresh_tokens(async_session_maker, user.id))
    assert all(token.revoked for token in tokens)


def test_inactive_user_blocked(client, async_session_maker):
    _register_user(client, email="inactive@example.com")
    login_response = _login_user(client, email="inactive@example.com")
    access_token = login_response.json()["access_token"]

    user = _run(_get_user_by_email(async_session_maker, "inactive@example.com"))
    _run(_set_user_active(async_session_maker, user.id, False))

    me_response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_response.status_code == 400


def test_cors_preflight_allows_frontend_origin(client):
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )
