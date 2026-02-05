import base64
import hashlib
import secrets
import urllib.parse
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_token_hash,
    generate_verification_token,
    get_password_hash,
    verify_password,
)
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import (
    MessageResponse,
    ResendVerificationRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    VerifyEmailRequest,
)
from pydantic import BaseModel
from app.services.email import send_verification_email
from jose import jwt

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

router = APIRouter()


def _build_google_auth_url(redirect_to: str, state: str, code_challenge: str) -> str:
    scopes = settings.google_oauth_scopes or "openid email profile"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    # Forward redirect target via state cookie, not via query param.
    return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"


def _safe_redirect_path(value: str | None) -> str:
    if not value or not value.startswith("/"):
        return "/"
    if value.startswith("//"):
        return "/"
    return value


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _clear_oauth_cookie(response: Response, name: str) -> None:
    response.delete_cookie(key=name, domain=_cookie_domain())


async def _exchange_google_code(code: str, code_verifier: str) -> dict:
    import httpx

    data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
        response.raise_for_status()
        return response.json()


async def _fetch_google_userinfo(access_token: str) -> dict:
    import httpx

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(GOOGLE_USERINFO_ENDPOINT, headers=headers)
        response.raise_for_status()
        return response.json()


def _create_exchange_code(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "google_exchange",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_exchange_code(token: str) -> str:
    payload = decode_token(token)
    if payload.get("type") != "google_exchange":
        raise ValueError("Invalid exchange token")
    return payload["sub"]


def _oauth_cookie_params():
    return {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": "lax",
        "domain": _cookie_domain(),
        "max_age": 600,
    }


@router.get("/auth/google/login")
async def google_login(request: Request):
    if not settings.google_client_id or not settings.google_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured",
        )

    redirect_to = _safe_redirect_path(request.query_params.get("redirect"))
    state = secrets.token_urlsafe(32)
    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)

    auth_url = _build_google_auth_url(redirect_to, state, code_challenge)
    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

    params = _oauth_cookie_params()
    response.set_cookie("google_oauth_state", state, **params)
    response.set_cookie("google_oauth_verifier", code_verifier, **params)
    response.set_cookie("google_oauth_redirect", redirect_to, **params)
    return response


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured",
        )

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    cookie_state = request.cookies.get("google_oauth_state")
    code_verifier = request.cookies.get("google_oauth_verifier")
    redirect_to = _safe_redirect_path(request.cookies.get("google_oauth_redirect"))

    response = RedirectResponse(url=f"{settings.frontend_url}/login", status_code=302)
    _clear_oauth_cookie(response, "google_oauth_state")
    _clear_oauth_cookie(response, "google_oauth_verifier")
    _clear_oauth_cookie(response, "google_oauth_redirect")

    if not code or not state or not cookie_state or not code_verifier:
        response.headers["Location"] = f"{settings.frontend_url}/login?error=google_oauth"
        return response

    if state != cookie_state:
        response.headers["Location"] = f"{settings.frontend_url}/login?error=google_oauth"
        return response

    try:
        token_data = await _exchange_google_code(code, code_verifier)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Missing access token")

        userinfo = await _fetch_google_userinfo(access_token)
        google_sub = userinfo.get("sub")
        email = userinfo.get("email")

        if not google_sub or not email:
            raise HTTPException(status_code=400, detail="Google userinfo incomplete")

        result = await db.execute(select(User).where(User.google_sub == google_sub))
        user = result.scalar_one_or_none()

        if not user:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user:
                user.google_sub = google_sub
                user.is_verified = True
                user.email_verification_token_hash = None
                user.email_verification_expires_at = None
                await db.commit()
            else:
                random_password = secrets.token_urlsafe(32)
                user = User(
                    email=email,
                    hashed_password=get_password_hash(random_password),
                    first_name=userinfo.get("given_name"),
                    last_name=userinfo.get("family_name"),
                    is_active=True,
                    is_verified=True,
                    google_sub=google_sub,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)

        exchange_code = _create_exchange_code(str(user.id))
        redirect_url = (
            f"{settings.frontend_url}/auth/google/callback?code="
            f"{urllib.parse.quote(exchange_code)}&redirect={urllib.parse.quote(redirect_to)}"
        )
        response.headers["Location"] = redirect_url
        return response
    except Exception:
        response.headers["Location"] = f"{settings.frontend_url}/login?error=google_oauth"
        return response


class GoogleCompleteRequest(BaseModel):
    exchange_code: str


@router.post("/auth/google/complete", response_model=TokenResponse)
async def google_complete(
    payload: GoogleCompleteRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    exchange_code = payload.exchange_code
    if not exchange_code:
        raise HTTPException(status_code=400, detail="Missing exchange code")

    try:
        user_id = UUID(_decode_exchange_code(exchange_code))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid exchange code")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})

    expires_at = datetime.utcnow() + timedelta(days=7)
    refresh_token_record = RefreshToken(
        user_id=user.id,
        token_hash=generate_token_hash(refresh_token),
        expires_at=expires_at,
    )
    db.add(refresh_token_record)
    await db.commit()

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        domain=_cookie_domain(),
    )

    return TokenResponse(access_token=access_token)


def _cookie_domain() -> str | None:
    if settings.cookie_domain:
        return settings.cookie_domain
    host = urlparse(settings.frontend_url).hostname
    if not host or host in {"localhost", "127.0.0.1"}:
        return None
    return f".{host.lstrip('.')}"


def _cookie_secure() -> bool:
    if settings.cookie_secure:
        return True
    return urlparse(settings.frontend_url).scheme == "https"


@router.post(
    "/auth/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user."""
    # Check if user already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        if not existing_user.is_verified:
            verification_token = generate_verification_token()
            existing_user.email_verification_token_hash = generate_token_hash(
                verification_token
            )
            existing_user.email_verification_expires_at = datetime.utcnow() + timedelta(
                hours=settings.email_verification_token_expire_hours
            )
            await db.commit()
            background_tasks.add_task(
                send_verification_email, existing_user.email, verification_token
            )
            return MessageResponse(
                message="If the account exists, a verification email was sent."
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    verification_token = generate_verification_token()
    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        email_verification_token_hash=generate_token_hash(verification_token),
        email_verification_expires_at=datetime.utcnow()
        + timedelta(hours=settings.email_verification_token_expire_hours),
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    background_tasks.add_task(
        send_verification_email, new_user.email, verification_token
    )

    return MessageResponse(message="User registered successfully")


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    user_credentials: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Login and receive access token."""
    # Get user by email
    result = await db.execute(select(User).where(User.email == user_credentials.email))
    user = result.scalar_one_or_none()

    # Verify credentials
    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified",
        )

    # Create access token
    access_token = create_access_token(data={"sub": user.email})

    # Create refresh token
    refresh_token = create_refresh_token(data={"sub": user.email})

    # Store refresh token in database (simplified - store token directly)
    expires_at = datetime.now() + timedelta(days=7)

    refresh_token_record = RefreshToken(
        user_id=user.id,
        token_hash=generate_token_hash(refresh_token),
        expires_at=expires_at,
    )
    db.add(refresh_token_record)
    await db.commit()

    # Set refresh token as httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        domain=_cookie_domain(),
    )

    return TokenResponse(access_token=access_token)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    # Get refresh token from httpOnly cookie
    refresh_token = request.cookies.get("refresh_token")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )

    if not refresh_token:
        raise credentials_exception

    try:
        # Decode refresh token
        payload = decode_token(refresh_token)
        email: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")

        if email is None or token_type != "refresh":
            raise credentials_exception
    except ValueError:
        raise credentials_exception

    # Get user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise credentials_exception

    # Verify refresh token exists in database and is not revoked
    refresh_token_hash = generate_token_hash(refresh_token)
    token_result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.expires_at > datetime.now(),
            (RefreshToken.token_hash == refresh_token_hash)
            | (RefreshToken.token_hash == refresh_token),  # legacy raw tokens
        )
    )
    stored_token = token_result.scalar_one_or_none()

    if not stored_token:
        raise credentials_exception

    # Revoke old refresh token
    stored_token.revoked = True

    # Create new access token
    access_token = create_access_token(data={"sub": user.email})

    # Create new refresh token (token rotation)
    new_refresh_token = create_refresh_token(data={"sub": user.email})
    expires_at = datetime.now() + timedelta(days=7)

    new_refresh_token_record = RefreshToken(
        user_id=user.id,
        token_hash=generate_token_hash(new_refresh_token),
        expires_at=expires_at,
    )
    db.add(new_refresh_token_record)
    await db.commit()

    # Set new refresh token as httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        domain=_cookie_domain(),
    )

    return TokenResponse(access_token=access_token)


@router.post("/auth/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a user's email using a one-time token."""
    token_hash = generate_token_hash(payload.token)
    result = await db.execute(
        select(User).where(User.email_verification_token_hash == token_hash)
    )
    user = result.scalar_one_or_none()

    if not user or not user.email_verification_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    if user.email_verification_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    if not user.is_verified:
        user.is_verified = True
        user.email_verification_token_hash = None
        user.email_verification_expires_at = None
        await db.commit()

    return MessageResponse(message="Email verified successfully")


@router.post("/auth/resend-verification", response_model=MessageResponse)
async def resend_verification(
    payload: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Resend email verification link if user exists and isn't verified."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user and not user.is_verified:
        verification_token = generate_verification_token()
        user.email_verification_token_hash = generate_token_hash(verification_token)
        user.email_verification_expires_at = datetime.utcnow() + timedelta(
            hours=settings.email_verification_token_expire_hours
        )
        await db.commit()
        background_tasks.add_task(
            send_verification_email, user.email, verification_token
        )

    return MessageResponse(
        message="If the account exists, a verification email was sent."
    )


@router.post("/auth/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Logout and revoke refresh token."""
    # Revoke all active refresh tokens for this user
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    tokens = result.scalars().all()

    for token in tokens:
        token.revoked = True

    await db.commit()

    # Clear refresh token cookie
    response.delete_cookie(key="refresh_token", domain=_cookie_domain())

    return MessageResponse(message="Logged out successfully")


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Get current user information."""
    return current_user
