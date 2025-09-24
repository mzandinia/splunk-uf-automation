"""
Configuration management for Splunk UF Auto-Restart System
Handles environment variables, YAML config files, and secure credential management
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class SecurityConfig(BaseSettings):
    """Security configuration settings"""

    api_key_required: bool = Field(
        default=False, description="Require API key for authentication"
    )
    api_key: Optional[str] = Field(
        default=None, description="API key for authentication"
    )
    allowed_ips: List[str] = Field(
        default=[], description="List of allowed IP addresses"
    )
    rate_limit_per_minute: int = Field(
        default=60, description="Rate limit per minute per IP"
    )
    jwt_secret_key: Optional[str] = Field(default=None, description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_hours: int = Field(
        default=24, description="JWT token expiration in hours"
    )

    class Config:
        env_prefix = "SECURITY_"


class AnsibleConfig(BaseSettings):
    """Ansible configuration settings"""

    playbooks_dir: str = Field(
        default="/home/ansible/ansible/playbooks",
        description="Ansible playbooks directory",
    )
    inventory_dir: str = Field(
        default="/home/ansible/ansible/inventory",
        description="Ansible inventory directory",
    )
    log_dir: str = Field(
        default="/home/ansible/server-logs/fastapi",
        description="FastAPI logs directory",
    )
    max_concurrent_tasks: int = Field(
        default=5, description="Maximum concurrent Ansible tasks"
    )
    ssh_password: Optional[str] = Field(
        default="ansible123",
        description="SSH password for ansible user",
    )
    ssh_user: str = Field(default="ansible", description="SSH user for Linux hosts")
    become: bool = Field(default=True, description="Use sudo/root for Ansible tasks")
    become_user: str = Field(
        default="ansible", description="User to become for Ansible tasks"
    )
    become_password: Optional[str] = Field(
        default=None, description="Sudo password for become when required"
    )
    winrm_user: str = Field(
        default="administrator", description="WinRM user for Windows hosts"
    )
    winrm_password: Optional[str] = Field(
        default=None, description="WinRM password for Windows hosts"
    )
    winrm_transport: str = Field(default="ntlm", description="WinRM transport method")
    winrm_server_cert_validation: str = Field(
        default="ignore", description="WinRM certificate validation"
    )

    class Config:
        env_prefix = "ANSIBLE_"


class AlertConfig(BaseSettings):
    """Alert configuration settings"""

    silent_threshold_minutes: int = Field(
        default=15, description="Minutes before UF is considered silent"
    )
    throttle_window_minutes: int = Field(
        default=30, description="Throttle window in minutes"
    )
    max_retry_attempts: int = Field(default=3, description="Maximum retry attempts")
    request_timeout_seconds: int = Field(
        default=30, description="Request timeout in seconds"
    )

    class Config:
        env_prefix = "ALERT_"


class LoggingConfig(BaseSettings):
    """Logging configuration settings"""

    level: str = Field(default="INFO", description="Logging level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format",
    )
    fastapi_log_file: str = Field(
        default="/home/ansible/server-logs/fastapi/uf_restart.log",
        description="FastAPI log file",
    )
    ansible_log_file: str = Field(
        default="/home/ansible/server-logs/ansible/playbook.log",
        description="Ansible log file",
    )
    max_file_size: int = Field(
        default=10485760, description="Maximum log file size in bytes (10MB)"
    )
    backup_count: int = Field(default=5, description="Number of backup log files")

    class Config:
        env_prefix = "LOGGING_"


class Settings(BaseSettings):
    """Main application settings"""

    # Application settings
    app_name: str = Field(
        default="Splunk UF Restart API", description="Application name"
    )
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    host: str = Field(default="0.0.0.0", description="Host to bind to")
    port: int = Field(default=7000, description="Port to bind to")
    workers: int = Field(default=4, description="Number of worker processes")

    # Component configurations
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    ansible: AnsibleConfig = Field(default_factory=AnsibleConfig)
    alert: AlertConfig = Field(default_factory=AlertConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @validator("security")
    def validate_security_config(cls, v):
        """Validate security configuration"""
        if v.api_key_required and not v.api_key:
            raise ValueError("API key is required when api_key_required is True")
        return v


def load_config_from_yaml(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Failed to load config from {config_path}: {e}")
        return {}


def _apply_yaml_config(settings: Settings, yaml_config: Dict[str, Any]) -> None:
    """Apply YAML configuration to settings object"""
    for section, values in yaml_config.items():
        if not (hasattr(settings, section) and isinstance(values, dict)):
            continue

        section_obj = getattr(settings, section)
        for key, value in values.items():
            if hasattr(section_obj, key):
                setattr(section_obj, key, value)


def get_settings(config_file: Optional[str] = None) -> Settings:
    """Get application settings with optional YAML config override"""
    settings = Settings()

    # Load YAML config if provided
    if config_file and os.path.exists(config_file):
        yaml_config = load_config_from_yaml(config_file)
        _apply_yaml_config(settings, yaml_config)

    return settings


# Global settings instance
settings = get_settings()


# Ensure required directories exist
def ensure_directories():
    """Ensure all required directories exist"""
    directories = [
        settings.ansible.playbooks_dir,
        settings.ansible.inventory_dir,
        settings.ansible.log_dir,
        os.path.dirname(settings.logging.fastapi_log_file),
        os.path.dirname(settings.logging.ansible_log_file),
    ]

    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


# Initialize directories on import
ensure_directories()
