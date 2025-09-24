# Splunk UF Automation - AWS Terraform Deployment

This directory contains Terraform configuration files for deploying the Splunk UF Automation system on AWS.

## Architecture Overview

The deployment creates the following infrastructure:

- **VPC** with public subnet in `us-east-1c`
- **3 EC2 Instances**:
  - FastAPI Server (t3.small) - Hosts the automation API
  - Splunk Enterprise (c5.xlarge) - Main Splunk server with alerting
  - Splunk UF (t2.micro) - Universal Forwarder for testing
- **Security Groups** with appropriate port configurations
- **IAM Roles** for EC2 instances
- **CloudWatch** logging and monitoring

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Terraform** >= 1.0 installed
3. **SSH Key Pair** named `demo-ansible-autoresponse` in AWS
4. **Public/Private key files** in the `keys/` directory

## Quick Start

### 1. Prepare SSH Keys

```bash
# Generate SSH key pair (if not exists)
ssh-keygen -t rsa -b 4096 -f /opt/splunk-uf-automation/terraform/keysdemo-ansible-autoresponse -N ""

# Import to AWS (if not already imported)
aws ec2 import-key-pair --key-name demo-ansible-autoresponse --public-key-material fileb://keys/demo-ansible-autoresponse.pub
```

### 2. Deploy Infrastructure

```bash
# Initialize Terraform
terraform init

# Review the plan
terraform plan

# Apply the configuration
terraform apply
```

### 3. Access the Services

After deployment, you can access:

- **FastAPI Server**: `http://<fastapi-public-ip>:8000`
- **Splunk Enterprise**: `http://<splunk-enterprise-public-ip>:8000`
- **API Documentation**: `http://<fastapi-public-ip>:8000/docs`

## Configuration

### Variables

Key variables in `terraform.tfvars`:

- `aws_region`: us-east-1
- `vpc_cidr`: 10.20.30.0/24
- `public_subnet_cidr`: 10.20.30.0/26
- `splunk_admin_password`: 12345678
- `ssh_key_name`: demo-ansible-autoresponse

### Instance Types

- **FastAPI Server**: t3.small (2 vCPU, 2GB RAM)
- **Splunk Enterprise**: c5.xlarge (4 vCPU, 8GB RAM)
- **Splunk UF**: t2.micro (1 vCPU, 1GB RAM)

### Security Groups

| Service | Port | Protocol | Source | Description |
|---------|------|----------|--------|-------------|
| FastAPI | 8000 | TCP | 0.0.0.0/0 | HTTP API |
| FastAPI | 22 | TCP | 0.0.0.0/0 | SSH |
| Splunk Enterprise | 8000 | TCP | 0.0.0.0/0 | Web UI |
| Splunk Enterprise | 22 | TCP | 0.0.0.0/0 | SSH |
| Splunk Enterprise | 8089 | TCP | 10.20.30.0/24 | Management |
| Splunk Enterprise | 9997 | TCP | 10.20.30.0/24 | Receiving |
| Splunk UF | 22 | TCP | 0.0.0.0/0 | SSH |
| Splunk UF | 8089 | TCP | 10.20.30.0/24 | Management |

## User Data Scripts

Each instance runs a user data script during startup:

### FastAPI Server (`user-data/fastapi-server.sh`)
- Installs Docker and Docker Compose
- Sets up the FastAPI application
- Configures CloudWatch logging
- Creates systemd service

### Splunk Enterprise (`user-data/splunk-enterprise.sh`)
- Installs Splunk Enterprise
- Configures deployment server
- Sets up custom alert action
- Creates UF context lookup

### Splunk UF (`user-data/splunk-uf.sh`)
- Installs Splunk Universal Forwarder
- Configures deployment server connection
- Sets up heartbeat monitoring
- Creates ansible user for automation

## Post-Deployment Configuration

### 1. Verify Services

```bash
# Check FastAPI health
curl http://<fastapi-ip>:8000/health

# Check Splunk Enterprise
curl http://<splunk-enterprise-ip>:8000/en-US/account/login

# Check Splunk UF status
ssh -i keys/demo-ansible-autoresponse.pem ubuntu@<splunk-uf-ip> "sudo /opt/splunkforwarder/bin/splunk status"
```

### 2. Test the Automation

1. **Simulate UF going silent**:
   ```bash
   ssh -i keys/demo-ansible-autoresponse.pem ubuntu@<splunk-uf-ip> "sudo /opt/splunk-uf-automation/simulate-silent.sh"
   ```

2. **Wait for alert** (runs every 5 minutes)

3. **Check FastAPI logs**:
   ```bash
   ssh -i keys/demo-ansible-autoresponse.pem ubuntu@<fastapi-ip> "docker logs splunk-uf-restart-api"
   ```

4. **Restore UF**:
   ```bash
   ssh -i keys/demo-ansible-autoresponse.pem ubuntu@<splunk-uf-ip> "sudo systemctl start SplunkForwarder"
   ```

## Monitoring

### CloudWatch Logs

- `/aws/ec2/splunk-uf-automation/fastapi` - FastAPI logs
- `/aws/ec2/splunk-uf-automation/splunk-enterprise` - Splunk Enterprise logs
- `/aws/ec2/splunk-uf-automation/splunk-uf` - Splunk UF logs

### CloudWatch Metrics

- `SplunkUF/FastAPI` - FastAPI server metrics
- `SplunkUF/Enterprise` - Splunk Enterprise metrics
- `SplunkUF/Forwarder` - Splunk UF metrics

## Troubleshooting

### Common Issues

1. **SSH Connection Failed**
   - Verify key pair exists in AWS
   - Check security group allows SSH (port 22)
   - Ensure private key has correct permissions (600)

2. **FastAPI Not Starting**
   - Check Docker service: `sudo systemctl status docker`
   - Check container logs: `docker logs splunk-uf-restart-api`
   - Verify user data script completed: `sudo tail -f /var/log/user-data.log`

3. **Splunk Not Accessible**
   - Check Splunk status: `sudo /opt/splunk/bin/splunk status`
   - Verify security groups allow required ports
   - Check Splunk logs: `sudo tail -f /opt/splunk/var/log/splunk/splunkd.log`

4. **Alert Not Triggering**
   - Verify UF is connected to deployment server
   - Check Splunk alert configuration
   - Review FastAPI logs for incoming requests

### Log Locations

- **FastAPI**: `/opt/splunk-uf-automation/logs/`
- **Splunk Enterprise**: `/opt/splunk/var/log/splunk/`
- **Splunk UF**: `/opt/splunkforwarder/var/log/splunk/`
- **System**: `/var/log/user-data.log`

## Cleanup

To destroy the infrastructure:

```bash
terraform destroy
```

**Warning**: This will permanently delete all resources and data.

## Cost Optimization

- Uses spot instances for cost savings
- EBS volumes are encrypted and can be resized
- CloudWatch logs have retention policies
- Consider using smaller instance types for development

## Security Considerations

- All EBS volumes are encrypted
- Security groups follow least privilege principle
- SSH access is restricted to specific key pair
- Splunk management ports are restricted to VPC
- Consider using AWS Secrets Manager for passwords in production

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review CloudWatch logs
3. Verify security group configurations
4. Check instance user data logs
