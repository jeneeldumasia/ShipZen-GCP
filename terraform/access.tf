# ── Cloudflare Access in front of the admin UIs ───────────────────────────────
# Grafana and ArgoCD are public hostnames protected only by an admin password,
# and ArgoCD can change anything in the cluster. Cloudflare Access (Zero Trust,
# free for up to 50 users) puts a login in front of them at Cloudflare's edge:
# only the emails below get through, after a one-time code sent to that email.
#
# Off until both variables are set (repository secrets CLOUDFLARE_ACCOUNT_ID and
# ADMIN_EMAILS). The Cloudflare API token also needs the account permission
# "Access: Apps and Policies: Edit". Setup: docs/operations/runbook.md.

variable "cloudflare_account_id" {
  description = "Cloudflare account ID (Dashboard > any zone > Overview > API). Empty disables Cloudflare Access."
  type        = string
  default     = ""
}

variable "access_allowed_emails" {
  description = "Comma-separated emails allowed through Cloudflare Access to Grafana and ArgoCD."
  type        = string
  default     = ""
}

locals {
  access_emails  = [for e in split(",", var.access_allowed_emails) : trimspace(e) if trimspace(e) != ""]
  access_enabled = var.cloudflare_account_id != "" && length(local.access_emails) > 0
  admin_hosts = {
    grafana = "grafana-shipzen.jeneeldumasia.codes"
    argocd  = "argocd.jeneeldumasia.codes"
  }
}

resource "cloudflare_zero_trust_access_application" "admin" {
  for_each = local.access_enabled ? local.admin_hosts : {}

  account_id       = var.cloudflare_account_id
  name             = "ShipZen ${each.key}"
  domain           = each.value
  type             = "self_hosted"
  session_duration = "24h"
}

resource "cloudflare_zero_trust_access_policy" "admin" {
  for_each = cloudflare_zero_trust_access_application.admin

  account_id     = var.cloudflare_account_id
  application_id = each.value.id
  name           = "ShipZen admins"
  precedence     = 1
  decision       = "allow"

  include {
    email = local.access_emails
  }
}
