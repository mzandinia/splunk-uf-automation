"""
Enhanced logging configuration with structured logging and correlation IDs
"""

import logging
import logging.handlers
import sys
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

import structlog


class CustomJSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation ID if available
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        # Add task ID if available
        if hasattr(record, "task_id"):
            log_entry["task_id"] = record.task_id

        # Add host information if available
        if hasattr(record, "host"):
            log_entry["host"] = record.host

        # Add component information if available
        if hasattr(record, "component"):
            log_entry["component"] = record.component

        # Add duration if available
        if hasattr(record, "duration"):
            log_entry["duration_seconds"] = record.duration

        # Add status if available
        if hasattr(record, "status"):
            log_entry["status"] = record.status

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
            ] and not key.startswith("_"):
                log_entry[key] = value

        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class LogSanitizer:
    """Sanitize logs to remove sensitive information"""

    SENSITIVE_PATTERNS = [
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

    @classmethod
    def sanitize_message(cls, message: str) -> str:
        """Sanitize log message"""
        # This is a simple implementation - in production, you might want more sophisticated regex patterns
        import re

        for pattern in cls.SENSITIVE_PATTERNS:
            if pattern in message.lower():
                # Replace the value after the pattern
                message = re.sub(
                    rf"({pattern}['\"\s]*[:=]['\"\s]*)([^'\"\s,}}]+)",
                    r"\1[REDACTED]",
                    message,
                    flags=re.IGNORECASE,
                )
        return message

    @classmethod
    def sanitize_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize dictionary data"""
        if not isinstance(data, dict):
            return data

        sanitized = {}
        for key, value in data.items():
            if any(pattern in key.lower() for pattern in cls.SENSITIVE_PATTERNS):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = cls.sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    cls.sanitize_dict(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized


class CorrelationFilter(logging.Filter):
    """Add correlation ID to log records"""

    def filter(self, record: logging.LogRecord) -> bool:
        # Try to get correlation ID from context variables
        try:
            import contextvars

            correlation_id = getattr(contextvars, "correlation_id", None)
            if correlation_id:
                record.correlation_id = correlation_id.get()
        except (AttributeError, LookupError):
            pass

        return True


def setup_rotating_file_handler(
    log_file: str, max_bytes: int = 50 * 1024 * 1024, backup_count: int = 10
) -> logging.handlers.RotatingFileHandler:
    """Setup rotating file handler with JSON formatting"""
    # Ensure log directory exists
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(CustomJSONFormatter())
    handler.addFilter(CorrelationFilter())
    return handler


def setup_console_handler(use_json: bool = False) -> logging.StreamHandler:
    """Setup console handler"""
    handler = logging.StreamHandler(sys.stdout)

    if use_json:
        handler.setFormatter(CustomJSONFormatter())
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)

    handler.addFilter(CorrelationFilter())
    return handler


def configure_logging(
    app_name: str = "uf_restart_api",
    log_level: str = "INFO",
    log_dir: str = "/home/ansible/server-logs/fastapi",
    use_json_console: bool = False,
) -> None:
    """Configure application logging"""

    # Create log directory if it doesn't exist
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # File handlers for different log types
    handlers = []

    # Main application log
    main_log_file = os.path.join(log_dir, f"{app_name}.log")
    handlers.append(setup_rotating_file_handler(main_log_file))

    # Error log (ERROR level and above)
    error_log_file = os.path.join(log_dir, f"{app_name}_error.log")
    error_handler = setup_rotating_file_handler(error_log_file)
    error_handler.setLevel(logging.ERROR)
    handlers.append(error_handler)

    # Security log
    security_log_file = os.path.join(log_dir, f"{app_name}_security.log")
    security_handler = setup_rotating_file_handler(security_log_file)
    security_handler.addFilter(lambda record: record.name == "security")
    handlers.append(security_handler)

    # Performance log
    performance_log_file = os.path.join(log_dir, f"{app_name}_performance.log")
    performance_handler = setup_rotating_file_handler(performance_log_file)
    performance_handler.addFilter(lambda record: record.name == "performance")
    handlers.append(performance_handler)

    # Console handler
    console_handler = setup_console_handler(use_json_console)
    handlers.append(console_handler)

    # Add all handlers to root logger
    for handler in handlers:
        root_logger.addHandler(handler)

    # Configure specific loggers
    configure_specific_loggers(log_level)


def configure_specific_loggers(log_level: str) -> None:
    """Configure specific loggers for different components"""

    # Security logger
    security_logger = logging.getLogger("security")
    security_logger.setLevel(logging.INFO)

    # Business logic logger
    business_logger = logging.getLogger("business")
    business_logger.setLevel(logging.INFO)

    # System logger
    system_logger = logging.getLogger("system")
    system_logger.setLevel(logging.INFO)

    # Performance logger
    performance_logger = logging.getLogger("performance")
    performance_logger.setLevel(logging.INFO)

    # Audit logger
    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(logging.INFO)

    # Error logger
    error_logger = logging.getLogger("error")
    error_logger.setLevel(logging.ERROR)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)


def get_logger(name: str, extra_context: Optional[Dict[str, Any]] = None):
    """Get a logger with optional extra context"""
    logger = logging.getLogger(name)

    if extra_context:
        # Create a LoggerAdapter to add extra context
        return LoggerAdapter(logger, extra_context)

    return logger


class LoggerAdapter(logging.LoggerAdapter):
    """Logger adapter to add extra context to all log messages"""

    def process(self, msg, kwargs):
        # Add extra context to the log record
        if "extra" not in kwargs:
            kwargs["extra"] = {}
        if self.extra:
            kwargs["extra"].update(self.extra)
        return msg, kwargs


class ContextualLogger:
    """Contextual logger that automatically adds context information"""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context = {}

    def set_context(self, **kwargs):
        """Set context for all future log messages"""
        self.context.update(kwargs)

    def clear_context(self):
        """Clear all context"""
        self.context.clear()

    def _log_with_context(self, level: int, msg: str, **kwargs):
        """Log message with current context"""
        extra = kwargs.get("extra", {})
        extra.update(self.context)
        kwargs["extra"] = extra
        self.logger.log(level, msg, **kwargs)

    def debug(self, msg: str, **kwargs):
        """Log debug message with context"""
        self._log_with_context(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        """Log info message with context"""
        self._log_with_context(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        """Log warning message with context"""
        self._log_with_context(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        """Log error message with context"""
        self._log_with_context(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        """Log critical message with context"""
        self._log_with_context(logging.CRITICAL, msg, **kwargs)


def configure_structured_logging():
    """Configure structlog for structured logging"""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


# Pre-configured logger instances for common use cases
def get_security_logger() -> ContextualLogger:
    """Get security logger instance"""
    return ContextualLogger("security")


def get_business_logger() -> ContextualLogger:
    """Get business logger instance"""
    return ContextualLogger("business")


def get_system_logger() -> ContextualLogger:
    """Get system logger instance"""
    return ContextualLogger("system")


def get_performance_logger() -> ContextualLogger:
    """Get performance logger instance"""
    return ContextualLogger("performance")


def get_audit_logger() -> ContextualLogger:
    """Get audit logger instance"""
    return ContextualLogger("audit")


def get_error_logger() -> ContextualLogger:
    """Get error logger instance"""
    return ContextualLogger("error")
