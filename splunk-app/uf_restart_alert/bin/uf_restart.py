#!/usr/bin/env python3
"""
Custom Splunk Alert Action: UF Auto Restart
Sends alert data to FastAPI server for automated UF restart via Ansible
Enhanced with retry logic and comprehensive error handling
"""

import sys
import json
import time
import requests
import random
import uuid
from collections import OrderedDict


def log_message(level, message, correlation_id=None):
    """Enhanced logging with correlation ID support"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    correlation_part = f" - Correlation ID: {correlation_id}" if correlation_id else ""
    sys.stderr.write(f"{timestamp} - {level} - {message}{correlation_part}\n")


def calculate_backoff_delay(
    attempt, base_delay=1.0, backoff_factor=2.0, max_delay=60.0, jitter=True
):
    """Calculate exponential backoff delay with jitter"""
    delay = min(base_delay * (backoff_factor**attempt), max_delay)
    if jitter:
        delay *= 0.5 + random.random() * 0.5
    return delay


def validate_request_data(data):
    """Validate request data before sending"""
    required_fields = ["host", "ip", "alert_time"]
    for field in required_fields:
        if not data.get(field):
            raise ValueError(f"Missing required field: {field}")

    # Validate IP format
    ip = data.get("ip", "")
    if ip and not _is_valid_ip(ip):
        raise ValueError(f"Invalid IP address format: {ip}")

    # Validate host format
    host = data.get("host", "")
    if host and (
        len(host) > 253 or not host.replace("-", "").replace(".", "").isalnum()
    ):
        raise ValueError(f"Invalid hostname format: {host}")


def _is_valid_ip(ip):
    """Basic IP validation"""
    try:
        import ipaddress

        ipaddress.ip_address(ip)
        return True
    except (ImportError, ValueError):
        # Fallback for older Python versions or invalid IP
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit() or not 0 <= int(part) <= 255:
                return False
        return True


def _validate_and_prepare_request(body, correlation_id):
    """Validate request data and prepare body"""
    log_message("DEBUG", f"Request body: {body}", correlation_id)

    try:
        data = json.loads(body) if isinstance(body, str) else body
        validate_request_data(data)
    except json.JSONDecodeError as e:
        log_message("ERROR", f"Request validation failed: {str(e)}", correlation_id)
        return None

    # Prepare request body
    if sys.version_info >= (3, 0) and isinstance(body, str):
        return body.encode("utf-8")
    return body


def _create_session(user_agent, correlation_id):
    """Create and configure requests session"""
    session = requests.Session()
    session.headers.update(
        {
            "Content-Type": "application/json",
            "User-Agent": user_agent or "Splunk-UF-Restart/1.0",
            "X-Request-ID": correlation_id or str(uuid.uuid4()),
        }
    )
    return session


def _handle_response(response, correlation_id):
    """Handle successful response and log details"""
    log_message(
        "INFO",
        f"FastAPI server responded successfully (HTTP {response.status_code})",
        correlation_id,
    )

    try:
        response_data = response.json()
        if "id" in response_data:
            log_message(
                "INFO",
                f"Task created with ID: {response_data['id']}",
                correlation_id,
            )
    except Exception:
        pass  # Response might not be JSON


def _handle_request_error(exception, attempt):
    """Handle various request exceptions and return error message"""
    if isinstance(exception, requests.exceptions.Timeout):
        return f"Request timeout after 30 seconds (attempt {attempt + 1})"
    elif isinstance(exception, requests.exceptions.ConnectionError):
        return f"Connection error: {str(exception)} (attempt {attempt + 1})"
    elif isinstance(exception, requests.exceptions.RequestException):
        return f"Request error: {str(exception)} (attempt {attempt + 1})"
    else:
        return f"Unexpected error: {str(exception)} (attempt {attempt + 1})"


def _should_retry(response_status_code):
    """Determine if request should be retried based on status code or error"""
    if response_status_code:
        # Don't retry on 4xx client errors (except 429)
        return not (400 <= response_status_code < 500 and response_status_code != 429)
    return True  # Retry on connection/other errors


def _execute_single_request(session, url, request_body, correlation_id):
    """Execute a single HTTP request and return response or exception"""
    start_time = time.time()
    try:
        response = session.post(url, data=request_body, timeout=30, verify=False)
        duration = time.time() - start_time

        log_message(
            "INFO",
            f"Request completed in {duration:.2f}s with status {response.status_code}",
            correlation_id,
        )
        return response, None
    except Exception as e:
        return None, e


def send_restart_request(
    url, body, user_agent=None, max_retries=3, correlation_id=None
):
    """Send restart request to FastAPI server with retry logic"""
    if url is None:
        log_message("ERROR", "No URL provided", correlation_id)
        return False

    log_message(
        "INFO",
        f"Starting request to {url} with {len(body)} bytes payload",
        correlation_id,
    )

    # Validate and prepare request
    request_body = _validate_and_prepare_request(body, correlation_id)
    if request_body is None:
        return False

    # Create session
    session = _create_session(user_agent, correlation_id)
    last_error = None

    # Retry loop
    for attempt in range(max_retries + 1):
        log_message(
            "INFO",
            f"Request attempt {attempt + 1}/{max_retries + 1}",
            correlation_id,
        )

        response, exception = _execute_single_request(
            session, url, request_body, correlation_id
        )

        if response is not None:
            # Handle successful response
            if 200 <= response.status_code < 300:
                _handle_response(response, correlation_id)
                return True

            # Handle HTTP error response
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            log_message("ERROR", f"Server error: {error_msg}", correlation_id)
            last_error = error_msg

            if not _should_retry(response.status_code):
                log_message("ERROR", "Client error - not retrying", correlation_id)
                break
        else:
            # Handle request exception
            error_msg = _handle_request_error(exception, attempt)
            log_message("ERROR", error_msg, correlation_id)
            last_error = error_msg

        # Wait before retry (except on last attempt)
        if attempt < max_retries:
            delay = calculate_backoff_delay(attempt)
            log_message("INFO", f"Waiting {delay:.1f}s before retry", correlation_id)
            time.sleep(delay)

    log_message(
        "ERROR", f"All retry attempts failed. Last error: {last_error}", correlation_id
    )
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "--execute":
        log_message("FATAL", "Unsupported execution mode (expected --execute flag)")
        sys.exit(1)

    # Generate correlation ID for this alert action execution
    correlation_id = str(uuid.uuid4())

    try:
        settings = json.loads(sys.stdin.read())
        log_message(
            "INFO",
            f"Alert action triggered with settings: {json.dumps(settings, indent=2)}",
            correlation_id,
        )

        # Extract configuration
        config = settings.get("configuration", {})
        result = settings.get("result", {})

        log_message(
            "INFO",
            f"Processing alert for host: {result.get('host', 'unknown')}",
            correlation_id,
        )

        # Build FastAPI URL
        protocol = "https" if config.get("use_ssl") == "1" else "http"
        host = config.get("fastapi_host", "localhost")
        port = config.get("fastapi_port", "7000")
        endpoint = config.get("fastapi_endpoint", "/restart-uf")
        url = f"{protocol}://{host}:{port}{endpoint}"

        log_message("INFO", f"Target FastAPI URL: {url}", correlation_id)

        # Build request body with enhanced data
        body = OrderedDict(
            [
                ("alert_type", "uf_silent"),
                ("host", result.get("host", "")),
                ("ip", result.get("ip", "")),
                ("os_type", result.get("os_type", "unknown")),
                ("os_name", result.get("os_name", "")),
                ("minutes_silent", result.get("minutes_ago", "")),
                ("last_seen", result.get("last_seen_readable", "")),
                ("alert_time", result.get("alert_time", "")),
                ("action", "restart_uf"),
                ("splunk_correlation_id", correlation_id),  # Add correlation ID
            ]
        )

        # Get configuration values with defaults
        user_agent = config.get("user_agent", "Splunk-UF-Restart")
        max_retries = int(config.get("retry_count", "3"))

        log_message(
            "INFO",
            f"Sending restart request with {max_retries} max retries",
            correlation_id,
        )

        # Send request with enhanced retry logic
        success = send_restart_request(
            url,
            json.dumps(body),
            user_agent=user_agent,
            max_retries=max_retries,
            correlation_id=correlation_id,
        )

        if success:
            log_message(
                "INFO",
                f"Successfully sent restart request for {result.get('host', 'unknown')}",
                correlation_id,
            )
            sys.exit(0)  # Success
        else:
            log_message(
                "ERROR",
                f"Failed to send restart request for {result.get('host', 'unknown')}",
                correlation_id,
            )
            sys.exit(2)  # Request failed

    except json.JSONDecodeError as e:
        log_message("ERROR", f"Failed to parse JSON input: {str(e)}", correlation_id)
        sys.exit(3)  # JSON parsing error
    except KeyError as e:
        log_message(
            "ERROR", f"Missing required configuration key: {str(e)}", correlation_id
        )
        sys.exit(4)  # Configuration error
    except Exception as e:
        log_message("ERROR", f"Unexpected error: {str(e)}", correlation_id)
        sys.exit(5)  # Unexpected error
