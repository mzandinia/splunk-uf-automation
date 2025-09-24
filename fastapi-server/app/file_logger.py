"""
File-based logging system for Splunk UF Auto-Restart System
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path
import aiofiles
import asyncio
from dataclasses import dataclass, asdict

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class TaskData:
    """Task data structure for file logging"""

    id: str
    status: str
    host: str
    ip: str
    os_type: str
    os_name: Optional[str] = None
    minutes_silent: Optional[str] = None
    last_seen: Optional[str] = None
    alert_time: str = ""
    action: str = "restart_uf"
    started_at: str = ""
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


class FileLogger:
    """File-based logging system for tasks and system events"""

    def __init__(self):
        self.log_dir = Path(settings.logging.fastapi_log_file).parent
        self.tasks_file = self.log_dir / "tasks.jsonl"
        self.system_log_file = self.log_dir / "system_events.jsonl"
        self.stats_file = self.log_dir / "system_stats.json"

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize stats file if it doesn't exist
        if not self.stats_file.exists():
            self._init_stats_file()

    def _init_stats_file(self):
        """Initialize system stats file"""
        initial_stats = {
            "total_tasks": 0,
            "pending_tasks": 0,
            "running_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "success_rate": 0.0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.stats_file, "w") as f:
            json.dump(initial_stats, f, indent=2)

    async def _append_to_file(self, file_path: Path, data: Dict[str, Any]):
        """Append data to a JSONL file"""
        try:
            async with aiofiles.open(file_path, "a") as f:
                await f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to write to {file_path}: {e}")

    async def _read_jsonl_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Read all records from a JSONL file"""
        if not file_path.exists():
            return []

        records = []
        try:
            async with aiofiles.open(file_path, "r") as f:
                async for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")

        return records

    async def create_task(self, task_data: Dict[str, Any]) -> TaskData:
        """Create a new task and log it"""
        task = TaskData(**task_data)

        # Log task creation
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "task_created",
            "task_id": task.id,
            "host": task.host,
            "ip": task.ip,
            "os_type": task.os_type,
            "status": task.status,
            "action": task.action,
            "alert_time": task.alert_time,
            "data": asdict(task),
        }

        await self._append_to_file(self.tasks_file, log_entry)
        logger.info(f"Created task {task.id} for host {task.host}")

        return task

    async def get_task(self, task_id: str) -> Optional[TaskData]:
        """Get a task by ID"""
        records = await self._read_jsonl_file(self.tasks_file)

        for record in records:
            if record.get("task_id") == task_id:
                return TaskData(**record["data"])

        return None

    async def update_task(
        self, task_id: str, update_data: Dict[str, Any]
    ) -> Optional[TaskData]:
        """Update a task"""
        task = await self.get_task(task_id)
        if not task:
            return None

        # Update task data
        for key, value in update_data.items():
            if hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.now(timezone.utc).isoformat()

        # Log task update
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "task_updated",
            "task_id": task.id,
            "host": task.host,
            "ip": task.ip,
            "os_type": task.os_type,
            "status": task.status,
            "updates": update_data,
            "data": asdict(task),
        }

        await self._append_to_file(self.tasks_file, log_entry)
        logger.info(f"Updated task {task_id}")

        return task

    async def get_tasks(
        self, limit: int = 100, status: Optional[str] = None, host: Optional[str] = None
    ) -> List[TaskData]:
        """Get tasks with optional filtering"""
        records = await self._read_jsonl_file(self.tasks_file)

        # Filter by status and host
        filtered_records = []
        for record in records:
            if status and record.get("status") != status:
                continue
            if host and record.get("host") != host:
                continue
            filtered_records.append(record)

        # Sort by timestamp (newest first) and limit
        filtered_records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Return TaskData objects
        tasks = []
        for record in filtered_records[:limit]:
            if "data" in record:
                tasks.append(TaskData(**record["data"]))

        return tasks

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task (log deletion event)"""
        task = await self.get_task(task_id)
        if not task:
            return False

        # Log task deletion
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "task_deleted",
            "task_id": task.id,
            "host": task.host,
            "ip": task.ip,
            "os_type": task.os_type,
            "status": task.status,
        }

        await self._append_to_file(self.tasks_file, log_entry)
        logger.info(f"Deleted task {task_id}")

        return True

    async def get_active_tasks(self) -> List[TaskData]:
        """Get all active tasks (pending or running)"""
        pending_tasks = await self.get_tasks(status="pending")
        running_tasks = await self.get_tasks(status="running")
        return pending_tasks + running_tasks

    async def log_system_event(
        self,
        level: str,
        component: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        host: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        """Log a system event"""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "component": component,
            "message": message,
            "details": details or {},
            "host": host,
            "task_id": task_id,
            "event_type": "system_event",
        }

        await self._append_to_file(self.system_log_file, log_entry)
        logger.info(f"System event logged: {level} - {component} - {message}")

    async def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        try:
            async with aiofiles.open(self.stats_file, "r") as f:
                content = await f.read()
                return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to read system stats: {e}")
            return {
                "total_tasks": 0,
                "pending_tasks": 0,
                "running_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "success_rate": 0.0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

    async def update_system_stats(self):
        """Update system statistics based on current tasks"""
        tasks = await self.get_tasks(limit=10000)  # Get all tasks

        total_tasks = len(tasks)
        pending_tasks = len([t for t in tasks if t.status == "pending"])
        running_tasks = len([t for t in tasks if t.status == "running"])
        completed_tasks = len([t for t in tasks if t.status == "completed"])
        failed_tasks = len([t for t in tasks if t.status == "failed"])

        success_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        stats = {
            "total_tasks": total_tasks,
            "pending_tasks": pending_tasks,
            "running_tasks": running_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "success_rate": round(success_rate, 2),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        try:
            async with aiofiles.open(self.stats_file, "w") as f:
                await f.write(json.dumps(stats, indent=2))
        except Exception as e:
            logger.error(f"Failed to update system stats: {e}")


# Global file logger instance
file_logger = FileLogger()
