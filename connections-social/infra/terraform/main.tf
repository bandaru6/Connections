"""
Terraform IaC for the Connections Social production infrastructure.

Resources provisioned:
  - RDS PostgreSQL 16 (with pgvector extension support)
  - ElastiCache Redis 7 (rate limiting, job state, graph cache)
  - Security groups (least-privilege ingress rules)
  - DB subnet group + cache subnet group

Tesla relevance:
  This mirrors a production telemetry pipeline's data tier — a managed
  relational store (RDS) handles structured events and the ANN index
  (pgvector), while Redis handles high-frequency ephemeral state (rate
  counters, job status, leaderboard caches).

Usage:
  terraform init
  terraform plan -var="db_password=..." -var="vpc_id=vpc-..." \
                 -var='private_subnet_ids=["subnet-a","subnet-b"]' \
                 -var="app_security_group_id=sg-..."
  terraform apply
"""

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Recommended: enable S3 backend for team use
  # backend "s3" {
  #   bucket         = "connections-terraform-state"
  #   key            = "prod/terraform.tfstate"
  #   region         = "us-west-2"
  #   encrypt        = true
  #   dynamodb_table = "connections-terraform-locks"
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "connections-social"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Security Groups
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_security_group" "rds" {
  name        = "connections-${var.environment}-rds"
  description = "Allow PostgreSQL traffic from application layer only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from app SG"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_security_group_id]
  }

  egress {
    description = "Allow all outbound (for AWS service endpoints)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "connections-${var.environment}-rds" }
}

resource "aws_security_group" "redis" {
  name        = "connections-${var.environment}-redis"
  description = "Allow Redis traffic from application layer only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis from app SG"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.app_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "connections-${var.environment}-redis" }
}

# ─────────────────────────────────────────────────────────────────────────────
# RDS PostgreSQL — primary data store + pgvector ANN index
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name       = "connections-${var.environment}"
  subnet_ids = var.private_subnet_ids

  tags = { Name = "connections-${var.environment}-db-subnet-group" }
}

resource "aws_db_parameter_group" "postgres16" {
  name   = "connections-${var.environment}-pg16"
  family = "postgres16"

  # Enable pgvector extension (must be allowlisted before CREATE EXTENSION)
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,vector"
  }

  # Tuning: increase work_mem for ANN sorting (pgvector IVFFlat uses sorting)
  parameter {
    name  = "work_mem"
    value = "32768"  # 32MB per sort/hash operation
  }

  # Log slow queries for performance analysis (>1s threshold)
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  tags = { Name = "connections-${var.environment}-pg16-params" }
}

resource "aws_db_instance" "postgres" {
  identifier = "connections-${var.environment}"

  engine         = "postgres"
  engine_version = "16.1"
  instance_class = var.db_instance_class

  db_name  = "connections"
  username = "connections"
  password = var.db_password

  # Storage: General Purpose SSD (gp3) with autoscaling
  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  # Subnet + security group
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # Custom parameter group (enables pgvector)
  parameter_group_name = aws_db_parameter_group.postgres16.name

  # Availability + backups
  # Multi-AZ standby for automatic failover (<60s RTO) on AZ outage
  multi_az               = var.environment == "prod"
  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"  # UTC — outside peak ingest hours
  maintenance_window      = "sun:04:30-sun:05:30"

  # Prevent accidental deletion in production
  deletion_protection = var.environment == "prod"
  skip_final_snapshot = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "connections-prod-final" : null

  # Performance Insights for query diagnostics (7-day free tier)
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  tags = { Name = "connections-${var.environment}-postgres" }
}

# ─────────────────────────────────────────────────────────────────────────────
# ElastiCache Redis — rate limiting + job state + graph query cache
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_elasticache_subnet_group" "main" {
  name       = "connections-${var.environment}"
  subnet_ids = var.private_subnet_ids

  tags = { Name = "connections-${var.environment}-redis-subnet-group" }
}

resource "aws_elasticache_parameter_group" "redis7" {
  name   = "connections-${var.environment}-redis7"
  family = "redis7"

  # Persist rate-limit counters across Redis restarts
  # (prevents burst traffic on restart from bypassing rate limits)
  parameter {
    name  = "appendonly"
    value = "yes"
  }

  tags = { Name = "connections-${var.environment}-redis7-params" }
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "connections-${var.environment}"
  description          = "Redis for rate limiting, job state, and graph cache"

  node_type            = var.cache_node_type
  num_cache_clusters   = var.environment == "prod" ? 2 : 1  # primary + replica in prod
  parameter_group_name = aws_elasticache_parameter_group.redis7.name
  engine_version       = "7.1"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = false  # keep false; TLS adds ~5% latency for short ops

  # Automatic failover (requires num_cache_clusters > 1)
  automatic_failover_enabled = var.environment == "prod"

  # 1-day snapshot for recovery (rate-limit state is ephemeral, but job state matters)
  snapshot_retention_limit = 1
  snapshot_window          = "02:00-03:00"

  tags = { Name = "connections-${var.environment}-redis" }
}
