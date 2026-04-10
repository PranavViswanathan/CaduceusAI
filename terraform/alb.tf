locals {
  use_https = var.acm_certificate_arn != ""
}

# ─── ALB ──────────────────────────────────────────────────────────────────────

resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = true

  access_logs {
    bucket  = aws_s3_bucket.alb_logs.id
    prefix  = "alb"
    enabled = true
  }

  tags = { Name = "${var.project_name}-alb" }
}

# ─── S3 bucket for ALB access logs ───────────────────────────────────────────

resource "aws_s3_bucket" "alb_logs" {
  bucket        = "${var.project_name}-alb-logs-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
  tags          = { Name = "${var.project_name}-alb-logs" }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    filter {}
    expiration { days = 30 }
  }
}

data "aws_elb_service_account" "main" {}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = data.aws_elb_service_account.main.arn }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.alb_logs.arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
    }]
  })
}

# ─── Target Groups ────────────────────────────────────────────────────────────

resource "aws_lb_target_group" "patient_portal" {
  name        = "${var.project_name}-patient-portal"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 10
    matcher             = "200-399"
  }

  tags = { Name = "${var.project_name}-patient-portal-tg" }
}

resource "aws_lb_target_group" "doctor_portal" {
  name        = "${var.project_name}-doctor-portal"
  port        = 3001
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 10
    matcher             = "200-399"
  }

  tags = { Name = "${var.project_name}-doctor-portal-tg" }
}

resource "aws_lb_target_group" "patient_api" {
  name        = "${var.project_name}-patient-api"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 10
    matcher             = "200"
  }

  tags = { Name = "${var.project_name}-patient-api-tg" }
}

resource "aws_lb_target_group" "doctor_api" {
  name        = "${var.project_name}-doctor-api"
  port        = 8002
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 10
    matcher             = "200"
  }

  tags = { Name = "${var.project_name}-doctor-api-tg" }
}

resource "aws_lb_target_group" "postcare_api" {
  name        = "${var.project_name}-postcare-api"
  port        = 8003
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 10
    matcher             = "200"
  }

  tags = { Name = "${var.project_name}-postcare-api-tg" }
}

# ─── HTTP Listener (redirect to HTTPS or serve directly) ─────────────────────

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.use_https ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = local.use_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "forward" {
      for_each = local.use_https ? [] : [1]
      content {
        target_group {
          arn = aws_lb_target_group.patient_portal.arn
        }
      }
    }
  }
}

# ─── HTTPS Listener ───────────────────────────────────────────────────────────

resource "aws_lb_listener" "https" {
  count = local.use_https ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.patient_portal.arn
  }
}

locals {
  # Use HTTPS listener if available, else HTTP
  main_listener_arn = local.use_https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}

# ─── Listener Rules ───────────────────────────────────────────────────────────

# /api/patient/* → patient-api
resource "aws_lb_listener_rule" "patient_api" {
  listener_arn = local.main_listener_arn
  priority     = 10

  condition {
    path_pattern { values = ["/api/patient/*"] }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.patient_api.arn
  }
}

# /api/doctor/* → doctor-api
resource "aws_lb_listener_rule" "doctor_api" {
  listener_arn = local.main_listener_arn
  priority     = 20

  condition {
    path_pattern { values = ["/api/doctor/*"] }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.doctor_api.arn
  }
}

# /api/postcare/* → postcare-api
resource "aws_lb_listener_rule" "postcare_api" {
  listener_arn = local.main_listener_arn
  priority     = 30

  condition {
    path_pattern { values = ["/api/postcare/*"] }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.postcare_api.arn
  }
}

# doctor.* host header → doctor-portal (only useful when domain_name is set)
resource "aws_lb_listener_rule" "doctor_portal" {
  count        = var.domain_name != "" ? 1 : 0
  listener_arn = local.main_listener_arn
  priority     = 40

  condition {
    host_header { values = ["doctor.${var.domain_name}"] }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.doctor_portal.arn
  }
}
