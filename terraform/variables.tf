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

variable "github_token" {
  description = "GitHub Personal Access Token for ArgoCD to access private repositories. Needs 'repo' scope."
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_app_id" {
  description = "GitHub App ID for ArgoCD repository access (preferred over PAT)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_app_installation_id" {
  description = "GitHub App Installation ID"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_app_private_key" {
  description = "GitHub App Private Key (PEM format)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "platform_machine_type" {
  description = "GCE machine type for the platform node pool"
  type        = string
  default     = "e2-standard-4"  # 4 vCPUs, 16GB RAM, ~$100/month per node
  # Options:
  #   e2-standard-2: 2 vCPUs, 8GB RAM, ~$50/month (budget, may be tight)
  #   e2-standard-4: 4 vCPUs, 16GB RAM, ~$100/month (recommended for dev/test)
  #   n2-standard-4: 4 vCPUs, 16GB RAM, ~$121/month (better performance)
  #   n2-standard-8: 8 vCPUs, 32GB RAM, ~$242/month (overkill for this workload)
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
