from datetime import datetime, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_verification_token,
    generate_token_hash,
    get_password_hash,
    verify_password,
)
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.email import send_verification_email
from app.schemas.auth import (
    MessageResponse,
    ResendVerificationRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    VerifyEmailRequest,
)

router = APIRouter()


@router.post("/auth/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
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

    background_tasks.add_task(send_verification_email, new_user.email, verification_token)

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
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days in seconds
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
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days in seconds
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
        background_tasks.add_task(send_verification_email, user.email, verification_token)

    return MessageResponse(message="If the account exists, a verification email was sent.")


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
    response.delete_cookie(key="refresh_token")

    return MessageResponse(message="Logged out successfully")


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Get current user information."""
    return current_user
