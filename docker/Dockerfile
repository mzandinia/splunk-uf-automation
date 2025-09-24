# Multi-stage build for FastAPI + Ansible container
FROM python:3.12-slim AS base

# Install system dependencies from Nexus
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install system dependencies
RUN apt-get update && apt-get install -y curl \
    openssh-client \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

# Install Ansible
RUN pip install --no-cache-dir ansible-core==2.15.0

# Stage 2: Application stage
FROM base

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY fastapi-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY fastapi-server/app ./app

# Create ansible user with specific UID/GID
RUN groupadd -g 1204 ansible && \
    useradd -m -s /bin/bash -u 1204 -g 1204 ansible && \
    usermod -aG sudo ansible && \
    chown -R ansible:ansible /home/ansible

# Create necessary directories as root (before switching to ansible user)
RUN mkdir -p \
    /home/ansible/ansible/playbooks \
    /home/ansible/ansible/inventory \
    /home/ansible/server-logs/fastapi \
    /home/ansible/server-logs/ansible

# Set permissions as root - use 755 for directories so the ansible user can create files
RUN chown -R ansible:ansible \
    /home/ansible/ansible/playbooks \
    /home/ansible/ansible/inventory \
    /home/ansible/server-logs/fastapi \
    /home/ansible/server-logs/ansible

RUN chmod 775 \
    /home/ansible/ansible/playbooks \
    /home/ansible/ansible/inventory \
    /home/ansible/server-logs/fastapi \
    /home/ansible/server-logs/ansible

# Switch to ansible user
USER ansible


# Environment variables
ENV ANSIBLE_PLAYBOOKS_DIR=/home/ansible/ansible/playbooks
ENV ANSIBLE_INVENTORY_DIR=/home/ansible/ansible/inventory
ENV FASTAPI_LOG_DIR=/home/ansible/server-logs/fastapi
ENV ANSIBLE_LOG_DIR=/home/ansible/server-logs/ansible
ENV MAX_CONCURRENT_TASKS=5
ENV PYTHONPATH=/app
ENV LOGGING_FASTAPI_LOG_FILE=/home/ansible/server-logs/fastapi/uf_restart.log

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7000/health || exit 1

# Expose port
EXPOSE 7000

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7000", "--workers", "4"]
