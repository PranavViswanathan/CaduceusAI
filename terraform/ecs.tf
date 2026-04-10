# ─── Cluster ──────────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${var.project_name}-cluster" }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ─── Shared locals ────────────────────────────────────────────────────────────

locals {
  db_url    = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/${var.db_name}"
  redis_url = "redis://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379"
  ollama_url = "http://${aws_instance.ollama.private_ip}:11434"

  common_env = [
    { name = "DATABASE_URL",    value = local.db_url },
    { name = "REDIS_URL",       value = local.redis_url },
    { name = "OLLAMA_URL",      value = local.ollama_url },
    { name = "JWT_SECRET",      value = var.jwt_secret },
    { name = "FERNET_KEY",      value = var.fernet_key },
    { name = "INTERNAL_API_KEY", value = var.internal_api_key },
  ]

  log_config = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = "/ecs/${var.project_name}"
      awslogs-region        = var.aws_region
      awslogs-stream-prefix = "ecs"
    }
  }

  alb_dns = aws_lb.main.dns_name
  base_url = var.domain_name != "" ? "https://${var.domain_name}" : "http://${local.alb_dns}"
}

# ─── patient-api ──────────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "patient_api" {
  family                   = "${var.project_name}-patient-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "patient-api"
    image     = var.patient_api_image != "" ? var.patient_api_image : "${aws_ecr_repository.services["patient-api"].repository_url}:latest"
    essential = true

    portMappings = [{ containerPort = 8001, protocol = "tcp" }]

    environment = concat(local.common_env, [
      { name = "PORT", value = "8001" }
    ])

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.services["patient-api"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "patient-api"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
      interval    = 30
      timeout     = 10
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_ecs_service" "patient_api" {
  name            = "${var.project_name}-patient-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.patient_api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.patient_api.arn
    container_name   = "patient-api"
    container_port   = 8001
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener_rule.patient_api]
}

# ─── doctor-api ───────────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "doctor_api" {
  family                   = "${var.project_name}-doctor-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "doctor-api"
    image     = var.doctor_api_image != "" ? var.doctor_api_image : "${aws_ecr_repository.services["doctor-api"].repository_url}:latest"
    essential = true

    portMappings = [{ containerPort = 8002, protocol = "tcp" }]

    environment = concat(local.common_env, [
      { name = "PORT", value = "8002" }
    ])

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.services["doctor-api"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "doctor-api"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8002/health || exit 1"]
      interval    = 30
      timeout     = 10
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_ecs_service" "doctor_api" {
  name            = "${var.project_name}-doctor-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.doctor_api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.doctor_api.arn
    container_name   = "doctor-api"
    container_port   = 8002
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener_rule.doctor_api]
}

# ─── postcare-api ─────────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "postcare_api" {
  family                   = "${var.project_name}-postcare-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "postcare-api"
    image     = var.postcare_api_image != "" ? var.postcare_api_image : "${aws_ecr_repository.services["postcare-api"].repository_url}:latest"
    essential = true

    portMappings = [{ containerPort = 8003, protocol = "tcp" }]

    environment = concat(local.common_env, [
      { name = "PORT", value = "8003" }
    ])

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.services["postcare-api"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "postcare-api"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8003/health || exit 1"]
      interval    = 30
      timeout     = 10
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_ecs_service" "postcare_api" {
  name            = "${var.project_name}-postcare-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.postcare_api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.postcare_api.arn
    container_name   = "postcare-api"
    container_port   = 8003
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener_rule.postcare_api]
}

# ─── patient-portal ───────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "patient_portal" {
  family                   = "${var.project_name}-patient-portal"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "patient-portal"
    image     = var.patient_portal_image != "" ? var.patient_portal_image : "${aws_ecr_repository.services["patient-portal"].repository_url}:latest"
    essential = true

    portMappings = [{ containerPort = 3000, protocol = "tcp" }]

    # NEXT_PUBLIC_* vars must match what the image was built with.
    # Rebuild images with these URLs if they differ from localhost.
    environment = [
      { name = "PORT", value = "3000" },
      { name = "NEXT_PUBLIC_PATIENT_API_URL",  value = "${local.base_url}/api/patient" },
      { name = "NEXT_PUBLIC_DOCTOR_API_URL",   value = "${local.base_url}/api/doctor" },
      { name = "NEXT_PUBLIC_POSTCARE_API_URL", value = "${local.base_url}/api/postcare" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.services["patient-portal"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "patient-portal"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:3000/ || exit 1"]
      interval    = 30
      timeout     = 10
      retries     = 3
      startPeriod = 120
    }
  }])
}

resource "aws_ecs_service" "patient_portal" {
  name            = "${var.project_name}-patient-portal"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.patient_portal.arn
  desired_count   = var.portal_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.patient_portal.arn
    container_name   = "patient-portal"
    container_port   = 3000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]
}

# ─── doctor-portal ────────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "doctor_portal" {
  family                   = "${var.project_name}-doctor-portal"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "doctor-portal"
    image     = var.doctor_portal_image != "" ? var.doctor_portal_image : "${aws_ecr_repository.services["doctor-portal"].repository_url}:latest"
    essential = true

    portMappings = [{ containerPort = 3001, protocol = "tcp" }]

    environment = [
      { name = "PORT", value = "3001" },
      { name = "NEXT_PUBLIC_PATIENT_API_URL",  value = "${local.base_url}/api/patient" },
      { name = "NEXT_PUBLIC_DOCTOR_API_URL",   value = "${local.base_url}/api/doctor" },
      { name = "NEXT_PUBLIC_POSTCARE_API_URL", value = "${local.base_url}/api/postcare" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.services["doctor-portal"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "doctor-portal"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:3001/ || exit 1"]
      interval    = 30
      timeout     = 10
      retries     = 3
      startPeriod = 120
    }
  }])
}

resource "aws_ecs_service" "doctor_portal" {
  name            = "${var.project_name}-doctor-portal"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.doctor_portal.arn
  desired_count   = var.portal_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.doctor_portal.arn
    container_name   = "doctor-portal"
    container_port   = 3001
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]
}

# ─── DB Migration Task (run once via aws ecs run-task) ───────────────────────

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.project_name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "migrate"
    image     = var.patient_api_image != "" ? var.patient_api_image : "${aws_ecr_repository.services["patient-api"].repository_url}:latest"
    essential = true
    command   = ["alembic", "upgrade", "head"]

    environment = [
      { name = "DATABASE_URL", value = local.db_url }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.services["migrate"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migrate"
      }
    }
  }])
}
