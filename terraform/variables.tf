# Variables for Splunk UF Automation Terraform Configuration

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name of the project for resource naming"
  type        = string
  default     = "splunk-uf-automation"
}

variable "availability_zone" {
  description = "Availability zone for resources"
  type        = string
  default     = "us-east-1c"
}

# VPC Configuration
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.20.30.0/24"
}

variable "public_subnet_cidr" {
  description = "CIDR block for public subnet"
  type        = string
  default     = "10.20.30.0/26"
}

# Instance Configuration
variable "fastapi_instance_type" {
  description = "Instance type for FastAPI server"
  type        = string
  default     = "t3.small"
}

variable "fastapi_ami_id" {
  description = "AMI ID for FastAPI server"
  type        = string
  default     = "ami-0360c520857e3138f"
}

variable "fastapi_private_ip" {
  description = "Private IP address for FastAPI server"
  type        = string
  default     = "10.20.30.10"
}

variable "splunk_enterprise_instance_type" {
  description = "Instance type for Splunk Enterprise server"
  type        = string
  default     = "c5.xlarge"
}

variable "splunk_enterprise_ami_id" {
  description = "AMI ID for Splunk Enterprise server"
  type        = string
  default     = "ami-0360c520857e3138f"
}

variable "splunk_enterprise_private_ip" {
  description = "Private IP address for Splunk Enterprise server"
  type        = string
  default     = "10.20.30.11"
}

variable "splunk_uf_instance_type" {
  description = "Instance type for Splunk UF server"
  type        = string
  default     = "t2.micro"
}

variable "splunk_uf_ami_id" {
  description = "AMI ID for Splunk UF server"
  type        = string
  default     = "ami-0360c520857e3138f"
}

variable "splunk_uf_private_ip" {
  description = "Private IP address for Splunk UF server"
  type        = string
  default     = "10.20.30.12"
}

# Storage Configuration
variable "ebs_volume_size" {
  description = "Size of EBS volumes in GB"
  type        = number
  default     = 20
}

# Security Configuration
variable "ansible_password" {
  description = "Password for ansible user"
  type        = string
  default     = "ansible123"
  sensitive   = true
}

variable "splunk_admin_password" {
  description = "Admin password for Splunk Enterprise"
  type        = string
  default     = "12345678"
  sensitive   = true
}


# Security Group Ports
variable "ssh_port" {
  description = "SSH port number"
  type        = number
  default     = 22
}

variable "fastapi_port" {
  description = "FastAPI HTTP port number"
  type        = number
  default     = 7000
}

variable "splunk_web_port" {
  description = "Splunk Web UI port number"
  type        = number
  default     = 8000
}

variable "splunk_management_port" {
  description = "Splunk Management port number"
  type        = number
  default     = 8089
}

variable "splunk_receiving_port" {
  description = "Splunk Receiving port number"
  type        = number
  default     = 9997
}

# Network Configuration
variable "all_cidr" {
  description = "CIDR block for all traffic (0.0.0.0/0)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "default_route_cidr" {
  description = "CIDR block for default route"
  type        = string
  default     = "0.0.0.0/0"
}

# Storage Configuration
variable "ebs_volume_type" {
  description = "Type of EBS volumes"
  type        = string
  default     = "gp3"
}

# Tags
variable "common_tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "Splunk UF Automation"
    Environment = "Production"
    ManagedBy   = "Terraform"
  }
}
