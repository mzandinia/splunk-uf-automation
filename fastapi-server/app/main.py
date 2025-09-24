"""
FastAPI Server for Splunk UF Auto-Restart System
Receives alerts from Splunk and triggers appropriate Ansible playbooks
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, IPvAnyAddress, validator
from typing import Optional, Dict, Any, List
import subprocess
import logging
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path
import yaml
import aiofiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import contextvars

# Import our modules
from .config import settings, ensure_directories
from .security import (
    security_manager,
    get_current_user,
    validate_alert_data,
    rate_limit_handler,
    require_rate_limit,
)
from .file_logger import file_logger, TaskData

# Import new error handling and logging modules
from .exceptions import (
    UFRestartException,
    AnsibleExecutionError,
    SSHConnectionError,
    ServiceRestartError,
    ValidationError,
    TimeoutError,
    CircuitBreakerOpenError,
)
from .utils import (
    RetryConfig,
    CircuitBreaker,
    retry_with_backoff,
    retry_decorator,
    sanitize_for_logging,
    test_connection,
    format_duration,
)
from .logging_config import (
    configure_logging,
    get_security_logger,
    get_business_logger,
    get_system_logger,
    get_performance_logger,
    get_audit_logger,
    get_error_logger,
    LogSanitizer,
)

# Configure enhanced logging
configure_logging(
    app_name="uf_restart_api",
    log_level=settings.logging.level,
    log_dir=(
        settings.logging.log_dir
        if hasattr(settings.logging, "log_dir")
        else "/home/ansible/server-logs/fastapi"
    ),
    use_json_console=False,
)

# Get specialized loggers
security_logger = get_security_logger()
business_logger = get_business_logger()
system_logger = get_system_logger()
performance_logger = get_performance_logger()
audit_logger = get_audit_logger()
error_logger = get_error_logger()

# Create correlation ID context variable
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)

# Create basic logger for backwards compatibility
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Automated UF restart service using Ansible",
    version=settings.version,
    debug=settings.debug,
)

# Add rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Add correlation ID to each request for tracing"""
    # Generate correlation ID
    correlation_id = str(uuid.uuid4())

    # Set in context variable
    correlation_id_var.set(correlation_id)

    # Log request start
    audit_logger.set_context(
        correlation_id=correlation_id,
        request_path=request.url.path,
        request_method=request.method,
        client_ip=request.client.host if request.client else "unknown",
    )

    start_time = time.time()
    audit_logger.info(f"Request started: {request.method} {request.url.path}")

    try:
        response = await call_next(request)

        # Log successful response
        duration = time.time() - start_time
        performance_logger.set_context(
            correlation_id=correlation_id,
            request_path=request.url.path,
            request_method=request.method,
            duration_seconds=duration,
            status_code=response.status_code,
        )
        performance_logger.info(
            f"Request completed successfully in {format_duration(duration)}"
        )

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    except Exception as e:
        # Log error
        duration = time.time() - start_time
        error_logger.set_context(
            correlation_id=correlation_id,
            request_path=request.url.path,
            request_method=request.method,
            duration_seconds=duration,
            error=str(e),
        )
        error_logger.error(
            f"Request failed after {format_duration(duration)}: {str(e)}"
        )
        raise
    finally:
        # Clear context
        audit_logger.clear_context()
        performance_logger.clear_context()
        error_logger.clear_context()


# Ensure directories exist
ensure_directories()


# Request models
class UFRestartRequest(BaseModel):
    """Model for UF restart request"""

    alert_type: str = Field(..., description="Type of alert")
    host: str = Field(..., description="Hostname of the UF")
    ip: str = Field(..., description="IP address of the UF")
    os_type: str = Field(..., description="Operating system type (linux/windows)")
    os_name: Optional[str] = Field(None, description="Full OS name")
    minutes_silent: Optional[str] = Field(None, description="Minutes since last seen")
    last_seen: Optional[str] = Field(None, description="Last seen timestamp")
    alert_time: str = Field(..., description="Alert generation time")
    action: str = Field(default="restart_uf", description="Action to perform")

    @validator("host")
    def validate_host(cls, v):
        return validate_hostname(v)

    @validator("ip")
    def validate_ip(cls, v):
        return validate_ip_address(v)

    @validator("os_type")
    def validate_os_type(cls, v):
        return validate_os_type(v)


class TaskStatus(BaseModel):
    """Model for task status response"""

    id: str
    status: str
    ip: str
    os_type: str
    minutes_silent: Optional[str] = None
    last_seen: Optional[str] = None
    alert_time: str
    action: str
    started_at: str
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: str
    updated_at: str

    @classmethod
    def from_task_data(cls, task: TaskData) -> "TaskStatus":
        """Create TaskStatus from TaskData"""
        return cls(
            id=task.id,
            status=task.status,
            ip=task.ip,
            os_type=task.os_type,
            minutes_silent=task.minutes_silent,
            last_seen=task.last_seen,
            alert_time=task.alert_time,
            action=task.action,
            started_at=task.started_at,
            completed_at=task.completed_at,
            result=task.result,
            error=task.error,
            retry_count=task.retry_count,
            max_retries=task.max_retries,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


# Task semaphore for concurrency control
task_semaphore = asyncio.Semaphore(settings.ansible.max_concurrent_tasks)


# Validation functions
def validate_hostname(hostname: str) -> str:
    """Validate hostname format"""
    if not hostname or len(hostname) > 253:
        raise ValueError("Invalid hostname")
    return hostname.strip().lower()


def validate_ip_address(ip: str) -> str:
    """Validate IP address format"""
    import ipaddress

    try:
        ipaddress.ip_address(ip)
        return ip
    except ValueError:
        raise ValueError("Invalid IP address format")


def validate_os_type(os_type: str) -> str:
    """Validate OS type"""
    valid_types = ["linux", "windows"]
    if os_type.lower() not in valid_types:
        raise ValueError(f"Invalid OS type. Must be one of: {', '.join(valid_types)}")
    return os_type.lower()


def get_playbook_path(os_type: str) -> str:
    """Get the appropriate playbook path based on OS type"""
    playbook_mapping = {
        "linux": "restart_uf_linux.yml",
        "windows": "restart_uf_windows.yml",
    }

    playbook_name = playbook_mapping.get(os_type.lower(), "restart_uf_generic.yml")
    playbook_path = os.path.join(settings.ansible.playbooks_dir, playbook_name)

    if not os.path.exists(playbook_path):
        logger.warning(f"Playbook {playbook_path} not found, using generic playbook")
        playbook_path = os.path.join(
            settings.ansible.playbooks_dir, "restart_uf_generic.yml"
        )

    return playbook_path


async def create_dynamic_inventory(host: str, ip: str, os_type: str) -> str:
    """Create a dynamic inventory file for Ansible"""
    inventory_data: Dict[str, Any] = {
        "all": {
            "hosts": {
                host: {
                    "ansible_host": ip,
                    "ansible_connection": (
                        "winrm" if os_type.lower() == "windows" else "ssh"
                    ),
                    "os_type": os_type,
                }
            }
        }
    }

    # Add OS-specific variables
    if os_type.lower() == "windows":
        inventory_data["all"]["hosts"][host].update(
            {
                "ansible_winrm_transport": settings.ansible.winrm_transport,
                "ansible_winrm_server_cert_validation": settings.ansible.winrm_server_cert_validation,
                "ansible_port": 5985,
                "ansible_user": settings.ansible.winrm_user,
                "ansible_password": settings.ansible.winrm_password,
            }
        )
    else:
        inventory_data["all"]["hosts"][host].update(
            {
                "ansible_user": settings.ansible.ssh_user,
                "ansible_password": settings.ansible.ssh_password,
                "ansible_become": settings.ansible.become,
                "ansible_become_user": settings.ansible.become_user,
                **(
                    {"ansible_become_password": settings.ansible.become_password}
                    if settings.ansible.become_password
                    else {}
                ),
            }
        )

    # Write inventory to file
    inventory_file = os.path.join(
        settings.ansible.inventory_dir,
        f"inventory_{host}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yml",
    )
    async with aiofiles.open(inventory_file, "w") as f:
        await f.write(yaml.dump(inventory_data, default_flow_style=False))

    return inventory_file


async def run_ansible_playbook(
    playbook_path: str, inventory_file: str, host: str, extra_vars: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute Ansible playbook asynchronously"""
    start_time = time.time()

    # Prepare Ansible command
    cmd = [
        "ansible-playbook",
        "-i",
        inventory_file,
        playbook_path,
        "--limit",
        host,
        "-e",
        json.dumps(extra_vars),
        "-vvv",  # More verbose output for debugging
    ]

    # Add SSH options for Linux/Unix hosts
    if extra_vars.get("os_type", "").lower() != "windows":
        cmd.extend(
            [
                "--ssh-common-args",
                "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
            ]
        )

    logger.info(f"Executing Ansible command: {' '.join(cmd)}")

    # Run the playbook
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "ANSIBLE_HOST_KEY_CHECKING": "False"},
    )

    stdout, stderr = await process.communicate()
    duration = time.time() - start_time

    result = {
        "return_code": process.returncode,
        "stdout": stdout.decode("utf-8"),
        "stderr": stderr.decode("utf-8"),
        "success": process.returncode == 0,
        "duration": duration,
    }

    # Log the result - disabled to use custom playbook logging instead
    # log_file = os.path.join(
    #     settings.ansible.log_dir,
    #     f"playbook_{host}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    # )
    # async with aiofiles.open(log_file, "w") as f:
    #     await f.write(json.dumps(result, indent=2))

    return result


async def process_uf_restart(request: UFRestartRequest, task_id: str):
    """Background task to process UF restart request"""
    async with task_semaphore:
        try:
            # Update task status to running
            await file_logger.update_task(task_id, {"status": "running"})
            logger.info(f"Processing UF restart for {request.host} ({request.ip})")

            # Log system event
            await file_logger.log_system_event(
                level="INFO",
                component="task_processor",
                message=f"Started UF restart task for {request.host}",
                host=request.host,
                task_id=task_id,
            )

            # Get appropriate playbook
            playbook_path = get_playbook_path(request.os_type)
            logger.info(f"Using playbook: {playbook_path}")

            # Create dynamic inventory
            inventory_file = await create_dynamic_inventory(
                request.host, request.ip, request.os_type
            )
            logger.info(f"Created inventory: {inventory_file}")

            # Prepare extra variables for Ansible
            extra_vars = {
                "target_host": request.host,
                "target_ip": request.ip,
                "os_type": request.os_type,
                "alert_time": request.alert_time,
                "minutes_silent": request.minutes_silent or "unknown",
                "restart_action": request.action,  # Renamed to avoid reserved word
                "correlation_id": task_id,  # Pass correlation ID for tracking
                "task_start_time": datetime.now(timezone.utc).isoformat(),
            }

            # Run the playbook
            result = await run_ansible_playbook(
                playbook_path, inventory_file, request.host, extra_vars
            )

            # Update task status
            if result["success"]:
                await file_logger.update_task(
                    task_id,
                    {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "result": result,
                    },
                )
                logger.info(f"Successfully restarted UF on {request.host}")

            else:
                await file_logger.update_task(
                    task_id,
                    {
                        "status": "failed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "result": result,
                        "error": result["stderr"],
                    },
                )
                logger.error(
                    f"Failed to restart UF on {request.host}: {result['stderr']}"
                )

            # Cleanup old inventory file after 1 hour
            _cleanup_task = asyncio.create_task(cleanup_file(inventory_file, 3600))

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error processing UF restart for {request.host}: {error_msg}")

            # Update task status
            await file_logger.update_task(
                task_id,
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": error_msg,
                },
            )

            # Log system event
            await file_logger.log_system_event(
                level="ERROR",
                component="task_processor",
                message=f"Failed to process UF restart for {request.host}: {error_msg}",
                host=request.host,
                task_id=task_id,
            )


async def cleanup_file(filepath: str, delay: int):
    """Delete a file after a specified delay"""
    await asyncio.sleep(delay)
    try:
        os.remove(filepath)
        logger.debug(f"Cleaned up file: {filepath}")
    except Exception as e:
        logger.warning(f"Failed to cleanup file {filepath}: {e}")


# API Endpoints


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": settings.app_name,
        "status": "running",
        "version": settings.version,
        "endpoints": [
            "/restart-uf",
            "/tasks",
            "/tasks/{task_id}",
            "/health",
        ],
    }


@app.post("/restart-uf", response_model=TaskStatus)
@limiter.limit("10/minute")
async def restart_uf(
    request: Request,
    restart_request: UFRestartRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Endpoint to trigger UF restart
    Receives alert from Splunk and initiates Ansible playbook execution
    """
    # Validate and sanitize input data
    try:
        validated_data = validate_alert_data(restart_request.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate task ID
    task_id = f"{validated_data['host']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Create task in database
    task_data = {
        "id": task_id,
        "status": "pending",
        "host": validated_data["host"],
        "ip": validated_data["ip"],
        "os_type": validated_data["os_type"],
        "os_name": validated_data.get("os_name"),
        "minutes_silent": validated_data.get("minutes_silent"),
        "last_seen": validated_data.get("last_seen"),
        "alert_time": validated_data["alert_time"],
        "action": validated_data["action"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "max_retries": settings.alert.max_retry_attempts,
    }

    task = await file_logger.create_task(task_data)

    # Add background task
    background_tasks.add_task(process_uf_restart, restart_request, task_id)

    logger.info(f"Created task {task_id} for UF restart on {validated_data['host']}")

    # Log system event
    await file_logger.log_system_event(
        level="INFO",
        component="api",
        message=f"Created UF restart task for {validated_data['host']}",
        host=validated_data["host"],
        task_id=task_id,
    )

    return TaskStatus.from_task_data(task)


@app.get("/tasks", response_model=List[TaskStatus])
@limiter.limit("30/minute")
async def get_tasks(
    request: Request,
    limit: int = 100,
    status: Optional[str] = None,
    host: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Get list of all tasks"""
    tasks = await file_logger.get_tasks(limit=limit, status=status, host=host)
    return [TaskStatus.from_task_data(task) for task in tasks]


@app.get("/tasks/{task_id}", response_model=TaskStatus)
@limiter.limit("60/minute")
async def get_task(
    request: Request,
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Get specific task status"""
    task = await file_logger.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatus.from_task_data(task)


@app.delete("/tasks/{task_id}")
@limiter.limit("10/minute")
async def delete_task(
    request: Request,
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Delete a task from logs"""
    success = await file_logger.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    # Log system event
    await file_logger.log_system_event(
        level="INFO",
        component="api",
        message=f"Deleted task {task_id}",
        task_id=task_id,
    )

    return {"message": f"Task {task_id} deleted"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Update and get system stats
    await file_logger.update_system_stats()
    stats = await file_logger.get_system_stats()

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system_stats": stats,
        "playbooks_dir": settings.ansible.playbooks_dir,
        "playbooks_available": (
            os.listdir(settings.ansible.playbooks_dir)
            if os.path.exists(settings.ansible.playbooks_dir)
            else []
        ),
    }


@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("FastAPI server starting up...")
    logger.info(f"Ansible playbooks directory: {settings.ansible.playbooks_dir}")
    logger.info(f"Ansible inventory directory: {settings.ansible.inventory_dir}")
    logger.info(f"Max concurrent tasks: {settings.ansible.max_concurrent_tasks}")

    # Log startup event
    await file_logger.log_system_event(
        level="INFO", component="system", message="FastAPI server started successfully"
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("FastAPI server shutting down...")

    # Get active tasks count
    active_tasks = await file_logger.get_active_tasks()
    logger.info(f"Active tasks: {len(active_tasks)}")

    # Log shutdown event
    await file_logger.log_system_event(
        level="INFO", component="system", message="FastAPI server shutting down"
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_level=settings.logging.level.lower(),
    )
