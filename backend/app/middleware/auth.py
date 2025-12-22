"""
JWT Authentication Middleware

Verifies JWT tokens issued by NextAuth.js (Auth.js v5) in the frontend.
Supports both session tokens and API tokens.
"""

import os
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from app.config import get_settings


# Security scheme
security = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    """Represents an authenticated user from JWT token."""
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: str = "USER"
    image: Optional[str] = None
    # Subscription info (passed from frontend)
    plan_tier: str = "none"  # "none", "creator", "studio"
    minutes_limit: int = 0
    minutes_used: float = 0.0
    minutes_remaining: float = 0.0
    is_paid: bool = False
    
    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"
    
    @property
    def has_quota(self) -> bool:
        """Check if user has remaining processing quota."""
        # Minutes can come from subscription OR top-ups; don't require "is_paid".
        return self.minutes_remaining > 0
    
    @property
    def is_priority(self) -> bool:
        """Check if user has priority queue access (Studio plan)."""
        return self.plan_tier == "studio"


def get_jwt_secret() -> str:
    """Get the JWT secret from environment or settings."""
    # NextAuth uses AUTH_SECRET for signing JWTs
    secret = os.getenv("AUTH_SECRET") or os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret not configured"
        )
    return secret


def verify_jwt_token(token: str) -> dict:
    """
    Verify and decode a JWT token.
    
    NextAuth.js v5 uses HS256 by default for JWT signing.
    The token contains user info in the payload.
    """
    try:
        secret = get_jwt_secret()
        settings = get_settings()
        algorithm = (settings.jwt.algorithm or "HS256").strip()
        
        # NextAuth tokens are signed with the AUTH_SECRET
        # They may be encrypted (JWE) or just signed (JWS)
        # For JWS tokens, we can decode directly
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            }
        )
        
        return payload
        
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_user_from_payload(payload: dict) -> AuthenticatedUser:
    """Extract user information from JWT payload."""
    # NextAuth JWT payload structure (extended with subscription info)
    # {
    #   "sub": "user_id",
    #   "email": "user@example.com",
    #   "name": "User Name",
    #   "picture": "...",
    #   "role": "USER",
    #   "plan_tier": "creator" | "studio" | "none",
    #   "minutes_limit": 60,
    #   "minutes_used": 15.5,
    #   "minutes_remaining": 44.5,
    #   "is_paid": true,
    #   "iat": ...,
    #   "exp": ...,
    # }
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return AuthenticatedUser(
        id=user_id,
        email=payload.get("email"),
        name=payload.get("name"),
        role=payload.get("role", "USER"),
        image=payload.get("picture"),
        plan_tier=payload.get("plan_tier", "none"),
        minutes_limit=payload.get("minutes_limit", 0),
        minutes_used=payload.get("minutes_used", 0.0),
        minutes_remaining=payload.get("minutes_remaining", 0.0),
        is_paid=payload.get("is_paid", False),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthenticatedUser:
    """
    Dependency to get the current authenticated user.
    
    Raises 401 if no valid token is provided.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: AuthenticatedUser = Depends(get_current_user)):
            return {"user_id": user.id}
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = verify_jwt_token(credentials.credentials)
    return extract_user_from_payload(payload)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[AuthenticatedUser]:
    """
    Dependency to optionally get the current user.
    
    Returns None if no token is provided (for public routes that
    may have enhanced features for authenticated users).
    
    Usage:
        @router.get("/public")
        async def public_route(user: Optional[AuthenticatedUser] = Depends(get_current_user_optional)):
            if user:
                return {"message": f"Hello, {user.name}!"}
            return {"message": "Hello, guest!"}
    """
    if not credentials:
        return None
    
    try:
        payload = verify_jwt_token(credentials.credentials)
        return extract_user_from_payload(payload)
    except HTTPException:
        return None


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    """
    Dependency to require admin role.
    
    Usage:
        @router.delete("/admin-only")
        async def admin_route(user: AuthenticatedUser = Depends(require_admin)):
            return {"admin_id": user.id}
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# API Key authentication (alternative to JWT for programmatic access)
API_KEY_HEADER = "X-API-Key"


async def get_api_key_user(request: Request) -> Optional[AuthenticatedUser]:
    """
    Authenticate using API key header.
    
    API keys should be stored in the database and associated with users.
    For now, this is a placeholder for future implementation.
    """
    api_key = request.headers.get(API_KEY_HEADER)
    if not api_key:
        return None
    
    # TODO: Look up API key in database and return associated user
    # For now, return None (not implemented)
    return None


async def get_current_user_or_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthenticatedUser:
    """
    Authenticate using either JWT token or API key.
    
    Useful for endpoints that need to support both browser and API access.
    """
    # Try JWT first
    if credentials:
        try:
            payload = verify_jwt_token(credentials.credentials)
            return extract_user_from_payload(payload)
        except HTTPException:
            pass
    
    # Try API key
    api_user = await get_api_key_user(request)
    if api_user:
        return api_user
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

