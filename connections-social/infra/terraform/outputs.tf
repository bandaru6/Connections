output "rds_endpoint" {
  description = "RDS PostgreSQL connection endpoint (host:port)"
  value       = "${aws_db_instance.postgres.address}:${aws_db_instance.postgres.port}"
  sensitive   = false
  # Use this to build DATABASE_URL:
  #   postgresql://connections:<password>@<rds_endpoint>/connections
}

output "rds_identifier" {
  description = "RDS instance identifier (for aws rds describe-db-instances)"
  value       = aws_db_instance.postgres.identifier
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint (host:port)"
  value       = "${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379"
  sensitive   = false
  # Use this to build REDIS_URL:
  #   redis://<redis_primary_endpoint>/0
}

output "redis_reader_endpoint" {
  description = "ElastiCache Redis reader endpoint (for read-only ops)"
  value       = "${aws_elasticache_replication_group.redis.reader_endpoint_address}:6379"
  sensitive   = false
}

output "rds_security_group_id" {
  description = "Security group ID for RDS — add to app SG egress if needed"
  value       = aws_security_group.rds.id
}

output "redis_security_group_id" {
  description = "Security group ID for Redis — add to app SG egress if needed"
  value       = aws_security_group.redis.id
}

output "connection_strings_note" {
  description = "How to configure the backend with these outputs"
  value       = <<-EOT
    Set the following environment variables (or K8s Secrets):
      DATABASE_URL=postgresql://connections:<db_password>@${aws_db_instance.postgres.address}:5432/connections
      REDIS_URL=redis://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0

    After first deploy, run the schema migrations:
      psql $DATABASE_URL -f infra/docker/init.sql
      psql $DATABASE_URL -f infra/docker/migrate_failed_ingests.sql
      psql $DATABASE_URL -f infra/docker/migrate_pgvector.sql   # requires pgvector extension
  EOT
  sensitive = false
}
