#!/bin/bash
# User data script for FastAPI server
# This script installs Docker, Docker Compose, and sets up the FastAPI application

set -e

ansible_password="ansible123"

# Update system
apt-get update -y

# Install required packages
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    python3-pip \
    python3-venv \
    unzip

# Install Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg --yes

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Check if ansible user exists and has correct UID/GID
NEED_RECREATE=false
if getent passwd ansible 2>/dev/null; then
    CURRENT_UID=$(getent passwd ansible | cut -d: -f3)
    CURRENT_GID=$(getent passwd ansible | cut -d: -f4)
    if [ "$CURRENT_UID" != "1204" ] || [ "$CURRENT_GID" != "1204" ]; then
        echo "ansible user exists with UID $CURRENT_UID, GID $CURRENT_GID"
        echo "Expected UID 1204, GID 1204 for container compatibility"
        echo "Deleting and recreating ansible user and group with correct UID/GID"
        NEED_RECREATE=true
    else
        echo "ansible user already exists with correct UID 1204, GID 1204"
    fi
else
    echo "ansible user does not exist, will create with UID 1204, GID 1204"
    NEED_RECREATE=true
fi

# Delete and recreate if needed
if [ "$NEED_RECREATE" = true ]; then
    # Delete user first (this will also remove from group)
    if getent passwd ansible 2>/dev/null; then
        echo "Deleting existing ansible user"
        userdel -r ansible
    fi

    # Delete group if it exists
    if getent group ansible 2>/dev/null; then
        echo "Deleting existing ansible group"
        groupdel ansible
    fi

    # Create group with correct GID
    echo "Creating ansible group with GID 1204"
    groupadd -g 1204 ansible

    # Create user with correct UID/GID
    echo "Creating ansible user with UID 1204"
    useradd -m -s /bin/bash -u 1204 -g 1204 ansible
    echo "Successfully created ansible user with UID 1204, GID 1204"
fi

# Add ansible user to docker group
if ! groups ansible | grep -q docker; then
    usermod -aG docker ansible
    echo "Added ansible user to docker group"
else
    echo "ansible user already in docker group"
fi

# Enable Docker to start on boot
systemctl enable docker
systemctl restart docker

# Remove existing splunk-uf-automation directory if it exists (to ensure clean clone)
if [ -d "/opt/splunk-uf-automation" ]; then
    echo "Removing existing splunk-uf-automation directory for clean clone"
    rm -rf /opt/splunk-uf-automation
fi

# Clone the repository fresh
echo "Cloning repository"
cd /opt
git clone https://github.com/mzandinia/splunk-uf-automation

# Delete unnecessary folders (ignore errors if they don't exist)
rm -rf /opt/splunk-uf-automation/splunk-app /opt/splunk-uf-automation/splunk-config 2> /dev/null || true

# Create necessary directories & set permissions
mkdir -p /home/ansible/ansible-inventory /home/ansible/server-logs/fastapi /home/ansible/server-logs/ansible /home/ansible/.ssh
chown -R ansible:ansible /opt/splunk-uf-automation
chown -R ansible:ansible /home/ansible
chmod 775 /home/ansible/ansible-inventory /home/ansible/server-logs/fastapi /home/ansible/server-logs/ansible /home/ansible/.ssh

# Set password for ansible user
echo "ansible:${ansible_password}" | chpasswd
echo "Set password for ansible user"

# Enable SSH password authentication
echo "Enabling SSH password authentication"
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl restart ssh 2> /dev/null || systemctl restart sshd 2> /dev/null || true
echo "Enabled SSH password authentication"

echo "Switching to ansible user for remaining operations..."

# Switch to ansible user and continue with the rest of the script
exec sudo -u ansible bash << EOF
echo "Now running as ansible user..."

# Building the fastapi container
cd /opt/splunk-uf-automation/docker
echo "Building FastAPI container..."
docker compose build --no-cache

# Running the fastapi container
echo "Starting FastAPI container..."
docker compose up -d

echo "FastAPI server setup completed successfully!"
EOF
