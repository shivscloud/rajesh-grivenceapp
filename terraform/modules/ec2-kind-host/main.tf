# ---------------------------------------------------------
# AMI: default to latest Ubuntu 22.04 LTS (allowed OS list
# includes Ubuntu). Override with var.ami_id if you need
# RHEL / Amazon2 / Windows instead.
# ---------------------------------------------------------
data "aws_ami" "ubuntu" {
  count       = var.ami_id == null ? 1 : 0
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  ami_id = var.ami_id != null ? var.ami_id : data.aws_ami.ubuntu[0].id
}

# ---------------------------------------------------------
# Security group: SSH + the single app port kind exposes
# on the host (mapped from frontend-service's NodePort 30080)
# ---------------------------------------------------------
resource "aws_security_group" "kind_host" {
  name        = "${var.name_prefix}-sg"
  description = "SSH + app access for the kind-on-EC2 host"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  ingress {
    description = "Grievance app (frontend-service via kind hostPort mapping)"
    from_port   = var.app_node_port_host
    to_port     = var.app_node_port_host
    protocol    = "tcp"
    cidr_blocks = [var.allowed_app_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-sg"
  }
}

# ---------------------------------------------------------
# EC2 instance running kind + the app.
# credit_specification is pinned to "standard" per policy -
# unlimited mode is not allowed for t2/t3 instances here.
# ---------------------------------------------------------
resource "aws_instance" "kind_host" {
  ami                    = local.ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.kind_host.id]

  associate_public_ip_address = true

  credit_specification {
    cpu_credits = "standard" # REQUIRED: unlimited mode is blocked/suspended per policy
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tpl", {
    repo_url           = var.repo_url
    app_node_port_host = var.app_node_port_host
    k8s_namespace      = var.k8s_namespace
    helm_release_name  = var.helm_release_name
    helm_chart_path    = var.helm_chart_path
  })

  tags = {
    Name = var.name_prefix
  }
}
