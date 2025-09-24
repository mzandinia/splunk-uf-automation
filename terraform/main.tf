# Main Terraform configuration for Splunk UF Automation System
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region = var.aws_region
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
}


# VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

# Public Subnet
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-subnet"
  }
}

# Route Table for Public Subnet
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = var.default_route_cidr
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

# Route Table Association
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Security Groups
resource "aws_security_group" "fastapi" {
  name_prefix = "${var.project_name}-fastapi-"
  vpc_id      = aws_vpc.main.id

  # SSH access from everywhere
  ingress {
    from_port   = var.ssh_port
    to_port     = var.ssh_port
    protocol    = "tcp"
    cidr_blocks = [var.all_cidr]
  }

  # FastAPI HTTP API from everywhere
  ingress {
    from_port   = var.fastapi_port
    to_port     = var.fastapi_port
    protocol    = "tcp"
    cidr_blocks = [var.all_cidr]
  }

  # All outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.all_cidr]
  }

  tags = {
    Name = "${var.project_name}-fastapi-sg"
  }
}

resource "aws_security_group" "splunk_enterprise" {
  name_prefix = "${var.project_name}-splunk-enterprise-"
  vpc_id      = aws_vpc.main.id

  # SSH access from everywhere
  ingress {
    from_port   = var.ssh_port
    to_port     = var.ssh_port
    protocol    = "tcp"
    cidr_blocks = [var.all_cidr]
  }

  # Splunk Web UI from everywhere
  ingress {
    from_port   = var.splunk_web_port
    to_port     = var.splunk_web_port
    protocol    = "tcp"
    cidr_blocks = [var.all_cidr]
  }

  # Splunk Management and Receiving within VPC
  ingress {
    from_port   = var.splunk_management_port
    to_port     = var.splunk_management_port
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    from_port   = var.splunk_receiving_port
    to_port     = var.splunk_receiving_port
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # All outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.all_cidr]
  }

  tags = {
    Name = "${var.project_name}-splunk-enterprise-sg"
  }
}

resource "aws_security_group" "splunk_uf" {
  name_prefix = "${var.project_name}-splunk-uf-"
  vpc_id      = aws_vpc.main.id

  # SSH access from everywhere
  ingress {
    from_port   = var.ssh_port
    to_port     = var.ssh_port
    protocol    = "tcp"
    cidr_blocks = [var.all_cidr]
  }

  # Splunk Management within VPC
  ingress {
    from_port   = var.splunk_management_port
    to_port     = var.splunk_management_port
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # All outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.all_cidr]
  }

  tags = {
    Name = "${var.project_name}-splunk-uf-sg"
  }
}

# IAM Role for EC2 instances
resource "aws_iam_role" "ec2_role" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ec2-role"
  }
}

# IAM Policy for EC2 instances
resource "aws_iam_role_policy" "ec2_policy" {
  name = "${var.project_name}-ec2-policy"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots"
        ]
        Resource = "*"
      }
    ]
  })
}

# IAM Instance Profile
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_role.name

  tags = {
    Name = "${var.project_name}-ec2-profile"
  }
}


# User data scripts
locals {
  fastapi_user_data = templatefile("${path.module}/user-data/fastapi-server.sh", {
    project_name     = var.project_name
    ansible_password = var.ansible_password
  })

  splunk_enterprise_user_data = templatefile("${path.module}/user-data/splunk-enterprise.sh", {
    project_name          = var.project_name
    splunk_admin_password = var.splunk_admin_password
    fastapi_server_ip     = aws_instance.fastapi.private_ip
    ansible_password      = var.ansible_password
  })

  splunk_uf_user_data = templatefile("${path.module}/user-data/splunk-uf.sh", {
    project_name         = var.project_name
    splunk_enterprise_ip = aws_instance.splunk_enterprise.private_ip
    ansible_password     = var.ansible_password
  })
}

# FastAPI Server Instance
resource "aws_instance" "fastapi" {
  ami                    = var.fastapi_ami_id
  instance_type          = var.fastapi_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.fastapi.id]
  private_ip             = var.fastapi_private_ip
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  user_data = local.fastapi_user_data

  root_block_device {
    volume_type           = var.ebs_volume_type
    volume_size           = var.ebs_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  # Add tags for better resource management
  tags = merge(
    {
      Name      = "${var.project_name}-fastapi-server"
      Type      = "FastAPI"
      Component = "Application"
    },
    var.common_tags
  )

  lifecycle {
    create_before_destroy = true
  }
}

# Splunk Enterprise Instance
resource "aws_instance" "splunk_enterprise" {
  ami                    = var.splunk_enterprise_ami_id
  instance_type          = var.splunk_enterprise_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.splunk_enterprise.id]
  private_ip             = var.splunk_enterprise_private_ip
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  user_data = local.splunk_enterprise_user_data

  root_block_device {
    volume_type           = var.ebs_volume_type
    volume_size           = var.ebs_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  # Add tags for better resource management
  tags = merge(
    {
      Name      = "${var.project_name}-splunk-enterprise"
      Type      = "SplunkEnterprise"
      Component = "Monitoring"
    },
    var.common_tags
  )

  lifecycle {
    create_before_destroy = true
  }
}

# Splunk UF Instance
resource "aws_instance" "splunk_uf" {
  ami                    = var.splunk_uf_ami_id
  instance_type          = var.splunk_uf_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.splunk_uf.id]
  private_ip             = var.splunk_uf_private_ip
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  user_data = local.splunk_uf_user_data

  root_block_device {
    volume_type           = var.ebs_volume_type
    volume_size           = var.ebs_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  # Add tags for better resource management
  tags = merge(
    {
      Name      = "${var.project_name}-splunk-uf"
      Type      = "SplunkUF"
      Component = "Forwarder"
    },
    var.common_tags
  )

  lifecycle {
    create_before_destroy = true
  }
}
