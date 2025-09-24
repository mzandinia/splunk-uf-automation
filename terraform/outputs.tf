# Outputs for Splunk UF Automation Infrastructure

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "public_subnet_id" {
  description = "ID of the public subnet"
  value       = aws_subnet.public.id
}

output "fastapi_server" {
  description = "FastAPI server information"
  value = {
    instance_id       = aws_instance.fastapi.id
    public_ip         = aws_instance.fastapi.public_ip
    private_ip        = aws_instance.fastapi.private_ip
    public_dns        = aws_instance.fastapi.public_dns
    private_dns       = aws_instance.fastapi.private_dns
    security_group_id = aws_security_group.fastapi.id
    api_url           = "http://${aws_instance.fastapi.public_ip}:7000"
    health_check_url  = "http://${aws_instance.fastapi.public_ip}:7000/health"
  }
}

output "splunk_enterprise_server" {
  description = "Splunk Enterprise server information"
  value = {
    instance_id       = aws_instance.splunk_enterprise.id
    public_ip         = aws_instance.splunk_enterprise.public_ip
    private_ip        = aws_instance.splunk_enterprise.private_ip
    public_dns        = aws_instance.splunk_enterprise.public_dns
    private_dns       = aws_instance.splunk_enterprise.private_dns
    security_group_id = aws_security_group.splunk_enterprise.id
    web_ui_url        = "http://${aws_instance.splunk_enterprise.public_ip}:8000"
    management_url    = "https://${aws_instance.splunk_enterprise.public_ip}:8089"
  }
}

output "splunk_uf_server" {
  description = "Splunk UF server information"
  value = {
    instance_id       = aws_instance.splunk_uf.id
    public_ip         = aws_instance.splunk_uf.public_ip
    private_ip        = aws_instance.splunk_uf.private_ip
    public_dns        = aws_instance.splunk_uf.public_dns
    private_dns       = aws_instance.splunk_uf.private_dns
    security_group_id = aws_security_group.splunk_uf.id
  }
}

output "ssh_connection_info" {
  description = "SSH connection information for all servers"
  value = {
    fastapi_server    = "ssh ansible@${aws_instance.fastapi.public_ip} (password: ansible123)"
    splunk_enterprise = "ssh ansible@${aws_instance.splunk_enterprise.public_ip} (password: ansible123)"
    splunk_uf         = "ssh ansible@${aws_instance.splunk_uf.public_ip} (password: ansible123)"
  }
  sensitive = true
}


output "deployment_summary" {
  description = "Deployment summary with all important URLs and information"
  value = {
    project_name = var.project_name
    region       = var.aws_region
    vpc_cidr     = var.vpc_cidr

    services = {
      fastapi = {
        url          = "http://${aws_instance.fastapi.public_ip}:7000"
        health_check = "http://${aws_instance.fastapi.public_ip}:7000/health"
        api_docs     = "http://${aws_instance.fastapi.public_ip}:7000/docs"
      }
      splunk_enterprise = {
        web_ui         = "http://${aws_instance.splunk_enterprise.public_ip}:8000"
        management     = "https://${aws_instance.splunk_enterprise.public_ip}:8089"
        admin_password = var.splunk_admin_password
      }
    }

    network = {
      vpc_id        = aws_vpc.main.id
      public_subnet = aws_subnet.public.id
    }

  }
  sensitive = true
}
