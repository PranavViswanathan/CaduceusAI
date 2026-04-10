resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project_name}-redis-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${var.project_name}-redis-subnet-group" }
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${var.project_name}-redis"
  description          = "Redis cache and queue for medical-ai-platform"

  node_type            = var.redis_node_type
  port                 = 6379
  parameter_group_name = "default.redis7"

  num_cache_clusters         = 2  # primary + 1 replica for HA
  automatic_failover_enabled = true
  multi_az_enabled           = true

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = false  # set true and update REDIS_URL to rediss:// if needed

  snapshot_retention_limit = 1
  snapshot_window          = "04:00-05:00"

  tags = { Name = "${var.project_name}-redis" }
}
