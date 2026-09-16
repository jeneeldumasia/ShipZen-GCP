variable "gcp_project" {
  description = "The GCP project ID to deploy the infrastructure into."
  type        = string
}

variable "gcp_region" {
  description = "The GCP region to deploy the infrastructure into."
  type        = string
  default     = "us-central1"
}

variable "pg_password" {
  description = "PostgreSQL password for the shipzen user. If empty, a default is used (not suitable for production)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "grafana_password" {
  description = "Grafana admin password. If empty, a default is used."
  type        = string
  default     = ""
  sensitive   = true
}

variable "redis_password" {
  description = "Redis password for authentication. Must be set for production."
  type        = string
  default     = ""
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token for DNS-01 challenge (cert-manager). Must have Zone:DNS:Edit permission."
  type        = string
  sensitive   = true
}

variable "platform_machine_type" {
  description = "GCE machine type for the platform node pool"
  type        = string
  default     = "e2-standard-4"
}

variable "use_cloud_sql" {
  description = "Set to true to provision a dedicated Cloud SQL PostgreSQL instance instead of in-cluster PostgreSQL."
  type        = bool
  default     = false
}

variable "cloud_sql_tier" {
  description = "Machine tier for Cloud SQL PostgreSQL."
  type        = string
  default     = "db-f1-micro"
}
