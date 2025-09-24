#!/bin/bash
# Deployment script for Splunk UF Automation on AWS

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."

    # Check if terraform is installed
    if ! command_exists terraform; then
        print_error "Terraform is not installed. Please install Terraform >= 1.0"
        exit 1
    fi

    # Check if aws cli is installed
    if ! command_exists aws; then
        print_error "AWS CLI is not installed. Please install AWS CLI"
        exit 1
    fi

    # Check if SSH key exists
    if [ ! -f "keys/demo-ansible-autoresponse" ]; then
        print_error "SSH private key not found. Please ensure keys/demo-ansible-autoresponse exists"
        exit 1
    fi

    if [ ! -f "keys/demo-ansible-autoresponse.pub" ]; then
        print_error "SSH public key not found. Please ensure keys/demo-ansible-autoresponse.pub exists"
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
        print_error "AWS credentials not configured. Please run 'aws configure'"
        exit 1
    fi

    print_success "All prerequisites met"
}

# Function to initialize Terraform
init_terraform() {
    print_status "Initializing Terraform..."
    terraform init
    print_success "Terraform initialized"
}

# Function to plan deployment
plan_deployment() {
    print_status "Planning deployment..."
    terraform plan -out=tfplan
    print_success "Deployment plan created"
}

# Function to apply deployment
apply_deployment() {
    print_status "Applying deployment..."
    terraform apply tfplan
    print_success "Deployment completed"
}

# Function to show outputs
show_outputs() {
    print_status "Deployment outputs:"
    echo ""
    terraform output
    echo ""

    # Extract key information
    FASTAPI_IP=$(terraform output -raw fastapi_server | jq -r '.public_ip')
    SPLUNK_IP=$(terraform output -raw splunk_enterprise_server | jq -r '.public_ip')
    UF_IP=$(terraform output -raw splunk_uf_server | jq -r '.public_ip')

    print_success "Deployment Summary:"
    echo "  FastAPI Server: http://$FASTAPI_IP:8000"
    echo "  Splunk Enterprise: http://$SPLUNK_IP:8000"
    echo "  Splunk UF: $UF_IP"
    echo ""
    echo "  SSH Commands:"
    echo "    FastAPI: ssh -i keys/demo-ansible-autoresponse.pem ubuntu@$FASTAPI_IP"
    echo "    Splunk Enterprise: ssh -i keys/demo-ansible-autoresponse.pem ubuntu@$SPLUNK_IP"
    echo "    Splunk UF: ssh -i keys/demo-ansible-autoresponse.pem ubuntu@$UF_IP"
}

# Function to wait for services
wait_for_services() {
    print_status "Waiting for services to start..."

    FASTAPI_IP=$(terraform output -raw fastapi_server | jq -r '.public_ip')
    SPLUNK_IP=$(terraform output -raw splunk_enterprise_server | jq -r '.public_ip')

    # Wait for FastAPI
    print_status "Waiting for FastAPI server..."
    for i in {1..30}; do
        if curl -f http://$FASTAPI_IP:8000/health >/dev/null 2>&1; then
            print_success "FastAPI server is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            print_warning "FastAPI server not ready after 5 minutes"
        fi
        sleep 10
    done

    # Wait for Splunk Enterprise
    print_status "Waiting for Splunk Enterprise..."
    for i in {1..30}; do
        if curl -f http://$SPLUNK_IP:8000/en-US/account/login >/dev/null 2>&1; then
            print_success "Splunk Enterprise is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            print_warning "Splunk Enterprise not ready after 5 minutes"
        fi
        sleep 10
    done
}

# Function to test the system
test_system() {
    print_status "Testing the system..."

    FASTAPI_IP=$(terraform output -raw fastapi_server | jq -r '.public_ip')
    UF_IP=$(terraform output -raw splunk_uf_server | jq -r '.public_ip')

    # Test FastAPI health
    print_status "Testing FastAPI health endpoint..."
    if curl -f http://$FASTAPI_IP:8000/health >/dev/null 2>&1; then
        print_success "FastAPI health check passed"
    else
        print_error "FastAPI health check failed"
    fi

    # Test UF status
    print_status "Testing Splunk UF status..."
    if ssh -i keys/demo-ansible-autoresponse.pem -o StrictHostKeyChecking=no ubuntu@$UF_IP "sudo /opt/splunkforwarder/bin/splunk status" >/dev/null 2>&1; then
        print_success "Splunk UF is running"
    else
        print_error "Splunk UF is not running"
    fi
}

# Function to show help
show_help() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  deploy    Deploy the infrastructure (default)"
    echo "  destroy   Destroy the infrastructure"
    echo "  plan      Show deployment plan without applying"
    echo "  status    Show current status"
    echo "  test      Test the deployed system"
    echo "  help      Show this help message"
    echo ""
}

# Function to destroy infrastructure
destroy_infrastructure() {
    print_warning "This will destroy all infrastructure and data!"
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        print_status "Destroying infrastructure..."
        terraform destroy -auto-approve
        print_success "Infrastructure destroyed"
    else
        print_status "Destruction cancelled"
    fi
}

# Function to show status
show_status() {
    print_status "Current infrastructure status:"
    terraform show
}

# Main script logic
main() {
    case "${1:-deploy}" in
        "deploy")
            check_prerequisites
            init_terraform
            plan_deployment
            apply_deployment
            show_outputs
            wait_for_services
            test_system
            print_success "Deployment completed successfully!"
            ;;
        "destroy")
            destroy_infrastructure
            ;;
        "plan")
            check_prerequisites
            init_terraform
            terraform plan
            ;;
        "status")
            show_status
            ;;
        "test")
            test_system
            ;;
        "help")
            show_help
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
