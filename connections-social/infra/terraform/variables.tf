variable "region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
  }
}

variable "db_instance_class" {
  description = "RDS instance type for PostgreSQL"
  type        = string
  default     = "db.t3.medium"
  # Interview note: t3.medium (2 vCPU, 4GB) handles ~200 concurrent connections
  # with pgvector cosine queries against 10K profiles. Upgrade to db.r6g.large
  # (2 vCPU, 16GB) when embedding memory pressure exceeds 4GB.
}

variable "cache_node_type" {
  description = "ElastiCache node type for Redis"
  type        = string
  default     = "cache.t3.micro"
  # cache.t3.micro handles rate-limit INCR/EXPIRE ops + job state for ~50 RPS.
  # Upgrade to cache.t3.small when used_memory_peak_mb > 400MB.
}

variable "db_password" {
  description = "PostgreSQL master password"
  type        = string
  sensitive   = true
  # Set via: TF_VAR_db_password=... terraform apply
  # Or store in AWS Secrets Manager and pull with data.aws_secretsmanager_secret_version
}

variable "vpc_id" {
  description = "VPC ID to deploy resources into"
  type        = string
  # Assumes an existing VPC — use data.aws_vpc to look up by tag if needed
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for RDS and ElastiCache (multi-AZ)"
  type        = list(string)
  # At least 2 subnets in different AZs for RDS Multi-AZ failover
}

variable "app_security_group_id" {
  description = "Security group ID attached to ECS/EC2 application instances"
  type        = string
  # RDS and ElastiCache ingress rules will allow traffic only from this SG
}

variable "db_allocated_storage_gb" {
  description = "Initial allocated storage for RDS PostgreSQL (GB)"
  type        = number
  default     = 20
  # 20GB covers ~10M embeddings at 2KB each. Enable storage_autoscaling.
}

variable "db_max_allocated_storage_gb" {
  description = "Max auto-scaled storage for RDS PostgreSQL (GB)"
  type        = number
  default     = 100
}

variable "backup_retention_days" {
  description = "RDS automated backup retention period (days)"
  type        = number
  default     = 7
  # 7 days allows replay / point-in-time recovery for incident investigation
}
