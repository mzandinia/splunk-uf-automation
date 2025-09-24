"""
Utility functions for retry logic and circuit breaker pattern
"""

import asyncio
import random
import time
from functools import wraps
from typing import Callable, Any, Optional, Type, Union, List
from datetime import datetime, timezone

from .exceptions import TimeoutError, CircuitBreakerOpenError


class RetryConfig:
    """Configuration for retry operations"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        timeout: Optional[float] = None,
        retryable_exceptions: Optional[List[Type[Exception]]] = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.timeout = timeout
        self.retryable_exceptions = retryable_exceptions or [Exception]


class CircuitBreaker:
    """Circuit breaker pattern implementation"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def _should_attempt_call(self) -> bool:
        """Check if call should be attempted based on circuit breaker state"""
        if self.state == "CLOSED":
            return True
        elif self.state == "OPEN":
            # Check if recovery timeout has passed
            if (
                self.last_failure_time
                and time.time() - self.last_failure_time >= self.recovery_timeout
            ):
                self.state = "HALF_OPEN"
                return True
            return False
        else:  # HALF_OPEN
            return True

    def _on_success(self):
        """Handle successful call"""
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = None

    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == "HALF_OPEN":
            self.state = "OPEN"
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        if not self._should_attempt_call():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN. Failure count: {self.failure_count}",
                failure_count=self.failure_count,
                last_failure_time=(
                    datetime.fromtimestamp(
                        self.last_failure_time, tz=timezone.utc
                    ).isoformat()
                    if self.last_failure_time
                    else None
                ),
            )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e


async def retry_with_backoff(
    func: Callable,
    config: RetryConfig,
    *args,
    **kwargs,
) -> Any:
    """
    Retry function with exponential backoff and jitter

    Args:
        func: Function to retry
        config: Retry configuration
        *args, **kwargs: Arguments to pass to function

    Returns:
        Result of successful function call

    Raises:
        Last exception if all retries exhausted
    """
    last_exception = None
    start_time = time.time()

    for attempt in range(config.max_retries + 1):
        try:
            # Check timeout
            if config.timeout and (time.time() - start_time) >= config.timeout:
                raise TimeoutError(
                    f"Operation timed out after {config.timeout} seconds",
                    timeout_seconds=int(config.timeout),
                    operation=func.__name__ if hasattr(func, "__name__") else str(func),
                )

            # Execute function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            return result

        except Exception as e:
            last_exception = e

            # Check if exception is retryable
            if not any(
                isinstance(e, exc_type) for exc_type in config.retryable_exceptions
            ):
                raise e

            # Don't retry on last attempt
            if attempt == config.max_retries:
                break

            # Calculate delay with exponential backoff
            delay = min(
                config.base_delay * (config.backoff_factor**attempt), config.max_delay
            )

            # Add jitter to prevent thundering herd
            if config.jitter:
                delay *= 0.5 + random.random() * 0.5

            await asyncio.sleep(delay)

    # All retries exhausted
    if last_exception:
        raise last_exception
    raise Exception("Retry logic failed without capturing exception")


def retry_decorator(config: RetryConfig):
    """
    Decorator for retry functionality

    Usage:
        @retry_decorator(RetryConfig(max_retries=3, base_delay=1.0))
        async def some_function():
            # function implementation
            pass
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_with_backoff(func, config, *args, **kwargs)

        return wrapper

    return decorator


class ConnectionPool:
    """Simple connection pool for managing SSH/HTTP connections"""

    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.connections = {}
        self.semaphore = asyncio.Semaphore(max_connections)

    async def get_connection(self, key: str, factory: Callable):
        """Get or create a connection"""
        async with self.semaphore:
            if key not in self.connections:
                self.connections[key] = await factory()
            return self.connections[key]

    async def close_connection(self, key: str):
        """Close and remove a connection"""
        if key in self.connections:
            connection = self.connections.pop(key)
            if hasattr(connection, "close"):
                await connection.close()

    async def close_all(self):
        """Close all connections"""
        for key in list(self.connections.keys()):
            await self.close_connection(key)


def sanitize_for_logging(data: Any, sensitive_keys: Optional[List[str]] = None) -> Any:
    """
    Sanitize data for logging by removing sensitive information

    Args:
        data: Data to sanitize (dict, list, string, etc.)
        sensitive_keys: List of keys to redact

    Returns:
        Sanitized data structure
    """
    if sensitive_keys is None:
        sensitive_keys = [
            "password",
            "passwd",
            "pass",
            "secret",
            "key",
            "token",
            "auth",
            "credential",
            "api_key",
            "private_key",
        ]

    def _sanitize_value(value):
        if isinstance(value, dict):
            return {
                k: (
                    "[REDACTED]"
                    if any(sensitive in k.lower() for sensitive in sensitive_keys)
                    else _sanitize_value(v)
                )
                for k, v in value.items()
            }
        elif isinstance(value, list):
            return [_sanitize_value(item) for item in value]
        elif isinstance(value, str) and any(
            sensitive in value.lower() for sensitive in sensitive_keys
        ):
            return "[REDACTED]"
        else:
            return value

    return _sanitize_value(data)


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> float:
    """Calculate backoff delay for retry attempts"""
    delay = min(base_delay * (backoff_factor**attempt), max_delay)
    if jitter:
        delay *= 0.5 + random.random() * 0.5
    return delay


async def test_connection(host: str, port: int, timeout: float = 5.0) -> bool:
    """Test network connectivity to a host and port"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"
