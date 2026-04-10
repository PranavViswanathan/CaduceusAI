output "alb_dns_name" {
  description = "ALB DNS name — point your domain's A/CNAME record here"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID (for Route 53 alias records)"
  value       = aws_lb.main.zone_id
}

output "patient_portal_url" {
  description = "Patient portal URL"
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

output "doctor_portal_url" {
  description = "Doctor portal URL"
  value       = var.domain_name != "" ? "https://doctor.${var.domain_name}" : "http://${aws_lb.main.dns_name} (add ?portal=doctor or use separate listener rule)"
}

output "ecr_repository_urls" {
  description = "ECR repository URLs — tag and push your images here"
  value = {
    for k, v in aws_ecr_repository.services : k => v.repository_url
  }
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = aws_db_instance.postgres.address
  sensitive   = false
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "ollama_private_ip" {
  description = "Ollama EC2 private IP (within VPC)"
  value       = aws_instance.ollama.private_ip
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "migrate_task_definition_arn" {
  description = "Run migrations: aws ecs run-task --cluster <cluster> --task-definition <arn> --launch-type FARGATE --network-configuration ..."
  value       = aws_ecs_task_definition.migrate.arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (for aws ecs run-task --network-configuration)"
  value       = aws_subnet.private[*].id
}

output "ecs_tasks_security_group_id" {
  description = "Security group ID for ECS tasks (needed for run-task)"
  value       = aws_security_group.ecs_tasks.id
}
