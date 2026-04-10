# ─── Latest Amazon Linux 2023 AMI (GPU-compatible) ───────────────────────────

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ─── Ollama EC2 Instance ──────────────────────────────────────────────────────

resource "aws_instance" "ollama" {
  ami           = data.aws_ami.amazon_linux_2023.id
  instance_type = var.ollama_instance_type

  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.ollama.id]
  iam_instance_profile   = aws_iam_instance_profile.ollama.name

  key_name = var.ollama_key_pair_name != "" ? var.ollama_key_pair_name : null

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.ollama_volume_size
    encrypted             = true
    delete_on_termination = false  # Preserve models across instance replacement
  }

  # Install CUDA drivers, Ollama, pull models, run as a service
  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -euxo pipefail

    # ── System updates ────────────────────────────────────────────────────────
    dnf update -y
    dnf install -y curl wget

    # ── NVIDIA driver + CUDA (for g4dn which has T4 GPU) ─────────────────────
    dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel9/x86_64/cuda-rhel9.repo
    dnf -y install cuda-toolkit-12-3 nvidia-driver-latest-dkms
    modprobe nvidia || true  # May require reboot; user_data continues

    # ── Ollama install ────────────────────────────────────────────────────────
    curl -fsSL https://ollama.ai/install.sh | sh

    # ── Systemd service ───────────────────────────────────────────────────────
    cat > /etc/systemd/system/ollama.service << 'UNIT'
    [Unit]
    Description=Ollama LLM Service
    After=network-online.target
    Wants=network-online.target

    [Service]
    ExecStart=/usr/local/bin/ollama serve
    User=ollama
    Group=ollama
    Restart=always
    RestartSec=3
    Environment=OLLAMA_HOST=0.0.0.0
    Environment=OLLAMA_MODELS=/var/lib/ollama/models

    [Install]
    WantedBy=multi-user.target
    UNIT

    useradd -r -s /bin/false -d /var/lib/ollama ollama || true
    mkdir -p /var/lib/ollama/models
    chown -R ollama:ollama /var/lib/ollama

    systemctl daemon-reload
    systemctl enable ollama
    systemctl start ollama

    # ── Pull models (runs in background; takes ~10 min for ~9GB) ─────────────
    # Wait for Ollama to be ready before pulling
    for i in $(seq 1 30); do
      curl -s http://localhost:11434/api/tags && break || sleep 5
    done

    su -s /bin/bash ollama -c "ollama pull llama3"
    su -s /bin/bash ollama -c "ollama pull mistral"

    echo "Ollama bootstrap complete" >> /var/log/ollama-init.log
  EOF
  )

  tags = {
    Name = "${var.project_name}-ollama"
    Role = "llm-inference"
  }

  lifecycle {
    # Prevent accidental replacement — model weights live on root EBS
    prevent_destroy = true
  }
}

# ─── IAM for Ollama instance (SSM access, CloudWatch logs) ───────────────────

resource "aws_iam_role" "ollama" {
  name = "${var.project_name}-ollama-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ollama_ssm" {
  role       = aws_iam_role.ollama.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ollama_cloudwatch" {
  role       = aws_iam_role.ollama.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "ollama" {
  name = "${var.project_name}-ollama-profile"
  role = aws_iam_role.ollama.name
}
