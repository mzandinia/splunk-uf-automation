#!/bin/bash
# User data script for Splunk Enterprise server
# This script installs Splunk Enterprise and configures it

set -e

fastapi_server_ip="10.20.30.10"
splunk_admin_password="12345678"
ansible_password="ansible123"

# Update system
apt-get update -y

# Install required packages
apt-get install -y \
    wget \
    curl \
    unzip \
    python3 \
    python3-pip \
    git

# Create splunk user for Splunk UF installation
if getent passwd splunk 2>/dev/null; then
    echo "splunk user already exists"
else
    echo "Creating splunk user"
    useradd -m -s /bin/bash splunk
    echo "Successfully created splunk user"
fi

if getent group splunk 2>/dev/null; then
    echo "splunk group already exists"
else
    echo "Creating splunk group"
    groupadd splunk
    echo "Successfully created splunk group"
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
ansible ALL=(ALL) NOPASSWD: /bin/systemctl restart Splunkd, /bin/systemctl start Splunkd, /bin/systemctl stop Splunkd, /bin/systemctl status Splunkd, /bin/systemctl is-active Splunkd
EOF

chmod 440 /etc/sudoers.d/90-ansible

# Set Splunk home directory
SPLUNK_HOME="/opt/splunk"

# Create Splunk directory
mkdir -p $SPLUNK_HOME 2> /dev/null

# Download Splunk Enterprise (replace with latest version)
cd /tmp
wget -O splunk-10.0.0-e8eb0c4654f8-linux-amd64.tgz "https://download.splunk.com/products/splunk/releases/10.0.0/linux/splunk-10.0.0-e8eb0c4654f8-linux-amd64.tgz"

# Install Splunk Enterprise
echo "Installing Splunk Enterprise"
tar xvzf /tmp/splunk-10.0.0-e8eb0c4654f8-linux-amd64.tgz -C /opt

# Create user-seed.conf for admin user setup
echo "Creating user-seed.conf for admin user setup"
mkdir -p /opt/splunk/etc/system/local 2> /dev/null
cat > /opt/splunk/etc/system/local/user-seed.conf << EOF
[user_info]
USERNAME = admin
PASSWORD = ${splunk_admin_password}
EOF
echo "Successfully created user-seed.conf"

# Change ownership to splunk user
echo "Changing ownership to splunk user"
chown -R splunk:splunk /opt/splunk
echo "Successfully changed ownership to splunk user"

# Enable Splunk to start on boot
echo "Enabling Splunk to start on boot"
/opt/splunk/bin/splunk enable boot-start --accept-license --no-prompt -systemd-managed 1 -user splunk -group splunk
echo "Successfully enabled Splunk boot start"

# Start Splunk
echo "Starting Splunk"
/opt/splunk/bin/splunk start
echo "Successfully started Splunk"

# Wait for Splunk to start
echo "Waiting for Splunk to start"
sleep 30
echo "Successfully waited for Splunk to start"

# Enable deployment server
echo "Enabling deployment server"
/opt/splunk/bin/splunk enable deploy-server -auth admin:${splunk_admin_password} 2> /dev/null
echo "Successfully enabled deployment server"

# Configure Splunk to receive data
echo "Configuring Splunk to receive data"
cat > /opt/splunk/etc/system/local/inputs.conf << EOF
[splunktcp://9997]
disabled = 0
connection_host = ip
EOF
echo "Successfully configured Splunk to receive data"

# Clone the repository fresh
echo "Cloning repository"
cd /tmp
git clone https://github.com/mzandinia/splunk-uf-automation
echo "Successfully cloned repository"

# Copy the custom alert action app to Splunk apps directory
echo "Copying custom alert action app to Splunk apps directory"
cp -r /tmp/splunk-uf-automation/splunk-app/uf_restart_alert /opt/splunk/etc/apps/
echo "Successfully copied custom alert action app to Splunk apps directory"

# Delete the repository
echo "Deleting repository"
rm -rf /tmp/splunk-uf-automation
echo "Successfully deleted repository"

# Make the script executable
echo "Making the script executable"
chmod +x /opt/splunk/etc/apps/uf_restart_alert/bin/uf_restart.py
echo "Successfully made the script executable"

# Create search/local directory
echo "Creating search/local directory"
mkdir /opt/splunk/etc/apps/search/local 2>/dev/null || true
echo "Successfully created search/local directory"

# Create savedsearches.conf
echo "Creating savedsearches.conf"
cat > /opt/splunk/etc/apps/search/local/savedsearches.conf << EOF
[UF_IP_OS_HOSTNAME]
action.email.useNSSubject = 1
action.webhook.enable_allowlist = 0
alert.track = 0
cron_schedule = */2 * * * *
dispatch.earliest_time = -24h@h
dispatch.latest_time = now
display.general.type = statistics
display.page.search.tab = statistics
display.visualizations.show = 0
enableSched = 1
request.ui_dispatch_app = search
request.ui_dispatch_view = search
search = | rest /services/deployment/server/clients splunk_server=local | table hostname ip utsname | rename hostname as host, utsname AS os_name| outputlookup create_context=system uf_ip_os.csv

[UF_Silent_Detection]
action.uf_restart = 1
action.uf_restart.param.fastapi_endpoint = /restart-uf
action.uf_restart.param.fastapi_host = ${fastapi_server_ip}
action.uf_restart.param.fastapi_port = 7000
action.uf_restart.param.retry_count = 5
action.uf_restart.param.timeout = 30
action.uf_restart.param.use_ssl = 0
action.webhook.enable_allowlist = 0
alert.suppress = 0
alert.track = 0
counttype = number of events
cron_schedule = */2 * * * *
dispatch.earliest_time = -24h@h
dispatch.latest_time = now
display.general.type = statistics
display.page.search.tab = statistics
enableSched = 1
quantity = 0
relation = greater than
request.ui_dispatch_app = search
request.ui_dispatch_view = search
search = | tstats latest(_time) as last_seen    WHERE index=_internal     BY host| eval minutes_ago=round((now()-last_seen)/60,0)| eval last_seen_readable=strftime(last_seen, "%Y-%m-%d %H:%M:%S")| table host minutes_ago last_seen_readable| join type=left host     [ | inputlookup uf_ip_os.csv | table host ip os_name ]| eval os_type=case(    match(os_name, "(?i)windows"), "windows",    match(os_name, "(?i)linux"), "linux",    match(os_name, "(?i)darwin|mac"), "macos",    1=1, "unknown")| eval alert_time=strftime(now(), "%Y-%m-%d %H:%M:%S")| table host ip os_type minutes_ago last_seen_readable alert_time| where minutes_ago > 2
EOF

# Set proper ownership
echo "Setting proper ownership"
chown -R splunk:splunk /opt/splunk
echo "Successfully set proper ownership"

# Restart Splunk to load the new app
echo "Restarting Splunk to load the new app"
/opt/splunk/bin/splunk restart
echo "Successfully restarted Splunk to load the new app"

# Verify installation
sleep 30
echo "Verifying Splunk Enterprise installation"
/opt/splunk/bin/splunk status
echo "Splunk Enterprise status check completed"
