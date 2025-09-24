#!/bin/bash
# User data script for Splunk UF server
# This script installs Splunk Universal Forwarder and configures it

set -e

splunk_enterprise_ip="10.20.30.11"
ansible_password="ansible123"

# Update system
apt-get update -y

# Install required packages
apt-get install -y \
    wget \
    curl \
    unzip \
    python3 \
    python3-pip

# Create splunkfwd user for Splunk UF installation
if getent passwd splunkfwd 2>/dev/null; then
    echo "splunkfwd user already exists"
else
    echo "Creating splunkfwd user"
    useradd -m -s /bin/bash splunkfwd
    echo "Successfully created splunkfwd user"
fi

if getent group splunkfwd 2>/dev/null; then
    echo "splunkfwd group already exists"
else
    echo "Creating splunkfwd group"
    groupadd splunkfwd
    echo "Successfully created splunkfwd group"
fi

# Create ansible user for FastAPI server access
if getent passwd ansible 2>/dev/null; then
    echo "ansible user already exists"
else
    echo "Creating ansible user"
    useradd -m -s /bin/bash ansible
    echo "Successfully created ansible user"
fi

# Add ansible user to sudo group
if ! groups ansible | grep -q sudo; then
    usermod -aG sudo ansible
    echo "Added ansible user to sudo group"
else
    echo "ansible user already in sudo group"
fi

# Set password for ansible user
echo "ansible:${ansible_password}" | chpasswd
echo "Set password for ansible user"

# Enable SSH password authentication
echo "Enabling SSH password authentication"
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Delete everything in /etc/ssh/sshd_config.d
echo "Deleting everything in /etc/ssh/sshd_config.d"
rm -f /etc/ssh/sshd_config/* 2> /dev/null || true
echo "Successfully deleted everything in /etc/ssh/sshd_config.d"

# Enable SSH password authentication in .d conf folder
echo "Enabling SSH password authentication in .d conf folder"
cat > /etc/ssh/sshd_config.d/01-password-authentication.conf << EOF
PasswordAuthentication yes
EOF
echo "Successfully enabled SSH password authentication in .d conf folder"

# Restart SSH
echo "Restarting SSH"
systemctl restart ssh 2> /dev/null || systemctl restart sshd 2> /dev/null || true
echo "Enabled SSH password authentication"

# Configure Sudoers for Ansible
cat > /etc/sudoers.d/90-ansible << EOF
ansible ALL=(ALL) NOPASSWD: /bin/systemctl restart SplunkForwarder, /bin/systemctl start SplunkForwarder, /bin/systemctl stop SplunkForwarder, /bin/systemctl status SplunkForwarder, /bin/systemctl is-active SplunkForwarder
EOF

chmod 440 /etc/sudoers.d/90-ansible

# Set Splunk home directory
SPLUNK_HOME="/opt/splunkforwarder"

# Create Splunk directory if it doesn't exist
if [ ! -d "$SPLUNK_HOME" ]; then
    echo "Creating Splunk directory at $SPLUNK_HOME"
    mkdir -p $SPLUNK_HOME 2> /dev/null
    echo "Successfully created Splunk directory"
else
    echo "Splunk directory already exists at $SPLUNK_HOME"
fi

# Download Splunk Universal Forwarder
echo "Downloading Splunk Universal Forwarder"
cd /tmp
SPLUNK_FILE="splunkforwarder-10.0.0-e8eb0c4654f8-linux-amd64.tgz"

if [ ! -f "$SPLUNK_FILE" ]; then
    echo "Downloading Splunk Universal Forwarder"
    wget -O $SPLUNK_FILE "https://download.splunk.com/products/universalforwarder/releases/10.0.0/linux/splunkforwarder-10.0.0-e8eb0c4654f8-linux-amd64.tgz"
    echo "Successfully downloaded Splunk Universal Forwarder"
else
    echo "Splunk Universal Forwarder already downloaded"
fi

# Extract Splunk UF to /opt directory
echo "Extracting Splunk Universal Forwarder"
tar xvzf /tmp/$SPLUNK_FILE -C /opt
echo "Successfully extracted Splunk Universal Forwarder"

# Change ownership to splunkfwd user
echo "Setting ownership of Splunk directory to splunkfwd user"
chown -R splunkfwd:splunkfwd /opt/splunkforwarder
echo "Successfully set ownership"

# Enable Splunk to start on boot using systemd
echo "Enabling Splunk to start on boot"
/opt/splunkforwarder/bin/splunk enable boot-start --accept-license --no-prompt -systemd-managed 1 -user splunkfwd -group splunkfwd
echo "Successfully enabled Splunk boot start"

# Configure deployment server
echo "Configuring deployment server"
/opt/splunkforwarder/bin/splunk set deploy-poll ${splunk_enterprise_ip}:8089
echo "Successfully configured deployment server"

# Configure Splunk UF to send data to Splunk Enterprise
echo "Configuring Splunk UF outputs"
cat > /opt/splunkforwarder/etc/system/local/outputs.conf << EOF
[tcpout]
defaultGroup = splunk_enterprise

[tcpout:splunk_enterprise]
server = ${splunk_enterprise_ip}:9997
EOF
echo "Successfully configured Splunk UF outputs"

# Restart Splunk UF to apply configuration
echo "Restarting Splunk UF to apply configuration"
/opt/splunkforwarder/bin/splunk restart
echo "Successfully restarted Splunk UF"

# Verify installation
sleep 20
echo "Verifying Splunk UF installation"
/opt/splunkforwarder/bin/splunk status
echo "Splunk UF status check completed"
