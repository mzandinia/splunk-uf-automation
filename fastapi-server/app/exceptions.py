"""
Custom exceptions for UF restart operations
"""

from typing import Optional, Dict, Any


class UFRestartException(Exception):
    """Base exception for UF restart operations"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AnsibleExecutionError(UFRestartException):
    """Ansible playbook execution failed"""

    def __init__(
        self,
        message: str,
        playbook_path: Optional[str] = None,
        return_code: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
    ):
        super().__init__(message)
        self.playbook_path = playbook_path
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.details = {
            "playbook_path": playbook_path,
            "return_code": return_code,
            "stdout": stdout,
            "stderr": stderr,
        }


class SSHConnectionError(UFRestartException):
    """SSH connection to target host failed"""

    def __init__(
        self,
        message: str,
        host: Optional[str] = None,
        ip: Optional[str] = None,
        port: Optional[int] = None,
    ):
        super().__init__(message)
        self.host = host
        self.ip = ip
        self.port = port
        self.details = {"host": host, "ip": ip, "port": port}


class ServiceRestartError(UFRestartException):
    """UF service restart failed"""

    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        host: Optional[str] = None,
        attempts: Optional[int] = None,
    ):
        super().__init__(message)
        self.service_name = service_name
        self.host = host
        self.attempts = attempts
        self.details = {
            "service_name": service_name,
            "host": host,
            "attempts": attempts,
        }


class ValidationError(UFRestartException):
    """Input validation failed"""

    def __init__(
        self, message: str, field: Optional[str] = None, value: Optional[str] = None
    ):
        super().__init__(message)
        self.field = field
        self.value = value
        self.details = {"field": field, "value": value}


class TimeoutError(UFRestartException):
    """Operation timed out"""

    def __init__(
        self,
        message: str,
        timeout_seconds: Optional[int] = None,
        operation: Optional[str] = None,
    ):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.operation = operation
        self.details = {"timeout_seconds": timeout_seconds, "operation": operation}


class CircuitBreakerOpenError(UFRestartException):
    """Circuit breaker is open, operation not allowed"""

    def __init__(
        self,
        message: str,
        failure_count: Optional[int] = None,
        last_failure_time: Optional[str] = None,
    ):
        super().__init__(message)
        self.failure_count = failure_count
        self.last_failure_time = last_failure_time
        self.details = {
            "failure_count": failure_count,
            "last_failure_time": last_failure_time,
        }
