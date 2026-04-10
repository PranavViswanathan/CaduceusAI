resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project_name}/${var.environment}/app-secrets"
  description             = "Application secrets for medical-ai-platform"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode({
    jwt_secret       = var.jwt_secret
    fernet_key       = var.fernet_key
    internal_api_key = var.internal_api_key
    db_password      = var.db_password
  })
}

# ─── Read back individual values via data source for task env injection ───────

data "aws_secretsmanager_secret_version" "app" {
  secret_id  = aws_secretsmanager_secret.app.id
  depends_on = [aws_secretsmanager_secret_version.app]
}

locals {
  app_secrets = jsondecode(data.aws_secretsmanager_secret_version.app.secret_string)
}
