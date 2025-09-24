"""
Security module for Splunk UF Auto-Restart System
Handles authentication, authorization, rate limiting, and input validation
"""

import hashlib
import hmac
import os
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import logging

from .config import settings

logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Security scheme
security = HTTPBearer(auto_error=False)


class SecurityManager:
    """Manages security operations including authentication and rate limiting"""

    def __init__(self):
        self.api_key = settings.security.api_key
        self.allowed_ips = set(settings.security.allowed_ips)
        self.rate_limit = settings.security.rate_limit_per_minute

    def validate_api_key(self, api_key: str) -> bool:
        """Validate API key"""
        if not self.api_key:
            return True  # No API key required

        return hmac.compare_digest(api_key, self.api_key)

    def validate_ip_address(self, request: Request) -> bool:
        """Validate IP address against allowed list"""
        if not self.allowed_ips:
            return True  # No IP restrictions

        client_ip = get_remote_address(request)
        return client_ip in self.allowed_ips

    def generate_api_key(self) -> str:
        """Generate a new API key"""
        timestamp = str(int(time.time()))
        random_data = os.urandom(32)
        key_data = f"{timestamp}:{random_data.hex()}"
        return hashlib.sha256(key_data.encode()).hexdigest()


# Global security manager instance
security_manager = SecurityManager()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Get current user from authentication credentials"""
    if not settings.security.api_key_required:
        return {"authenticated": True, "user": "anonymous"}

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not security_manager.validate_api_key(credentials.credentials):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"authenticated": True, "user": "api_user"}


def validate_request_source(request: Request) -> bool:
    """Validate that the request comes from an allowed source"""
    if not security_manager.validate_ip_address(request):
        logger.warning(f"Request from unauthorized IP: {get_remote_address(request)}")
        raise HTTPException(status_code=403, detail="IP address not allowed")

    return True


def get_rate_limiter() -> Limiter:
    """Get rate limiter instance"""
    return limiter


# Input validation functions
def validate_hostname(hostname: str) -> str:
    """Validate hostname format"""
    if not hostname or len(hostname) > 255:
        raise ValueError("Invalid hostname")

    # Basic hostname validation
    if not all(c.isalnum() or c in ".-" for c in hostname):
        raise ValueError("Hostname contains invalid characters")

    return hostname.lower()


def validate_ip_address(ip: str) -> str:
    """Validate IP address format"""
    import ipaddress

    try:
        ipaddress.ip_address(ip)
        return ip
    except ValueError:
        raise ValueError("Invalid IP address format")


def validate_os_type(os_type: str) -> str:
    """Validate operating system type"""
    valid_types = {"linux", "windows", "unknown"}
    os_type_lower = os_type.lower()

    if os_type_lower not in valid_types:
        raise ValueError(f"Invalid OS type. Must be one of: {', '.join(valid_types)}")

    return os_type_lower


def validate_alert_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize alert data"""
    validated_data = {}

    # Required fields
    required_fields = ["host", "ip", "os_type", "alert_time"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Validate and sanitize fields
    validated_data["host"] = validate_hostname(data["host"])
    validated_data["ip"] = validate_ip_address(data["ip"])
    validated_data["os_type"] = validate_os_type(data["os_type"])

    # Optional fields with defaults
    validated_data["alert_type"] = data.get("alert_type", "uf_silent")
    validated_data["os_name"] = data.get("os_name", "")
    validated_data["minutes_silent"] = data.get("minutes_silent", "unknown")
    validated_data["last_seen"] = data.get("last_seen", "")
    validated_data["alert_time"] = data["alert_time"]
    validated_data["action"] = data.get("action", "restart_uf")

    # Validate alert_time format
    try:
        datetime.fromisoformat(validated_data["alert_time"].replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid alert_time format. Use ISO format.")

    return validated_data


# Security middleware
class SecurityMiddleware:
    """Custom security middleware for additional validation"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)

            # Validate request source
            try:
                validate_request_source(request)
            except HTTPException as e:
                # Return error response
                response = {
                    "type": "http.response.start",
                    "status": e.status_code,
                    "headers": [[b"content-type", b"application/json"]],
                }
                await send(response)

                error_body = {"detail": e.detail}
                await send(
                    {
                        "type": "http.response.body",
                        "body": str(error_body).encode(),
                    }
                )
                return

        await self.app(scope, receive, send)


# Rate limit exceeded handler
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded events"""
    logger.warning(f"Rate limit exceeded for IP: {get_remote_address(request)}")
    return HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded: {exc.detail}",
        headers={"Retry-After": str(exc.retry_after)},
    )


# Security decorators
def require_authentication(func):
    """Decorator to require authentication for endpoints"""

    async def wrapper(*args, **kwargs):
        # This will be handled by the dependency injection
        return await func(*args, **kwargs)

    return wrapper


def require_rate_limit(rate: str):
    """Decorator to apply rate limiting to endpoints"""

    def decorator(func):
        return limiter.limit(rate)(func)

    return decorator


# Security utilities
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token"""
    from jose import jwt

    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            hours=settings.security.jwt_expiration_hours
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.security.jwt_secret_key,
        algorithm=settings.security.jwt_algorithm,
    )
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """Verify and decode a JWT token"""
    from jose import jwt, JWTError

    try:
        payload = jwt.decode(
            token,
            settings.security.jwt_secret_key,
            algorithms=[settings.security.jwt_algorithm],
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
