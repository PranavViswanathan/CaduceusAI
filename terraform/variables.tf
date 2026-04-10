variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (prod, staging, dev)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "medical-ai"
}

# ─── Networking ───────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

# ─── Domain / TLS ─────────────────────────────────────────────────────────────

variable "domain_name" {
  description = "Primary domain (e.g. example.com). Leave empty to use ALB DNS name."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ARN of an existing ACM certificate. Required if domain_name is set."
  type        = string
  default     = ""
}

# ─── Database ─────────────────────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 50
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "medical_ai"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "medical_user"
}

variable "db_password" {
  description = "PostgreSQL master password (store in Secrets Manager in prod)"
  type        = string
  sensitive   = true
}

# ─── Redis ────────────────────────────────────────────────────────────────────

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.t3.micro"
}

# ─── ECS / Fargate ────────────────────────────────────────────────────────────

variable "patient_api_image" {
  description = "Docker image URI for patient-api (ECR URI after push)"
  type        = string
  default     = ""
}

variable "doctor_api_image" {
  description = "Docker image URI for doctor-api"
  type        = string
  default     = ""
}

variable "postcare_api_image" {
  description = "Docker image URI for postcare-api"
  type        = string
  default     = ""
}

variable "patient_portal_image" {
  description = "Docker image URI for patient-portal (Next.js)"
  type        = string
  default     = ""
}

variable "doctor_portal_image" {
  description = "Docker image URI for doctor-portal (Next.js)"
  type        = string
  default     = ""
}

variable "api_desired_count" {
  description = "Desired task count for each API service"
  type        = number
  default     = 2
}

variable "portal_desired_count" {
  description = "Desired task count for each portal service"
  type        = number
  default     = 2
}

# ─── Ollama / GPU ─────────────────────────────────────────────────────────────

variable "ollama_instance_type" {
  description = "EC2 instance type for Ollama LLM inference (needs GPU)"
  type        = string
  default     = "g4dn.xlarge"
}

variable "ollama_volume_size" {
  description = "EBS volume size in GB for Ollama model storage"
  type        = number
  default     = 100
}

variable "ollama_key_pair_name" {
  description = "EC2 key pair name for SSH access to Ollama instance (optional)"
  type        = string
  default     = ""
}

# ─── Secrets ──────────────────────────────────────────────────────────────────

variable "jwt_secret" {
  description = "JWT signing secret (min 32 chars)"
  type        = string
  sensitive   = true
}

variable "fernet_key" {
  description = "Fernet AES-256 key for PHI encryption"
  type        = string
  sensitive   = true
}

variable "internal_api_key" {
  description = "Shared secret for inter-service authentication"
  type        = string
  sensitive   = true
}
