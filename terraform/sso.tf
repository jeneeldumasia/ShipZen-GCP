# ── GitHub sign-in (SSO) for Grafana and ArgoCD ───────────────────────────────
# Replaces the shared admin passwords with "Sign in with GitHub". Off until the
# OAuth app for that tool is configured; the admin passwords keep working
# either way (break-glass). Each tool needs its own GitHub OAuth app, because an
# OAuth app has a single callback URL:
#
#   Grafana: homepage https://grafana-shipzen.jeneeldumasia.codes
#            callback https://grafana-shipzen.jeneeldumasia.codes/login/github
#   ArgoCD:  homepage https://argocd.jeneeldumasia.codes
#            callback https://argocd.jeneeldumasia.codes/api/dex/callback
#
# Repository secrets: GRAFANA_GITHUB_CLIENT_ID / _SECRET and
# ARGOCD_GITHUB_CLIENT_ID / _SECRET. Who gets in:
#   Grafana: only the GitHub logins in sso_admin_github_logins (as Admin);
#            everyone else is refused (role_attribute_strict).
#   ArgoCD:  any GitHub account can complete the login, but only the emails in
#            ADMIN_EMAILS (access_allowed_emails) get a role: role:admin. The
#            default policy is empty, so anyone else sees nothing.
# Cloudflare Access (access.tf), if on, still sits in front of both.

variable "grafana_github_client_id" {
  description = "GitHub OAuth app client ID for Grafana sign-in. Empty keeps GitHub sign-in off."
  type        = string
  default     = ""
}

variable "grafana_github_client_secret" {
  description = "GitHub OAuth app client secret for Grafana sign-in."
  type        = string
  default     = ""
  sensitive   = true
}

variable "argocd_github_client_id" {
  description = "GitHub OAuth app client ID for ArgoCD sign-in (through Dex). Empty keeps GitHub sign-in off."
  type        = string
  default     = ""
}

variable "argocd_github_client_secret" {
  description = "GitHub OAuth app client secret for ArgoCD sign-in."
  type        = string
  default     = ""
  sensitive   = true
}

variable "sso_admin_github_logins" {
  description = "Comma-separated GitHub logins that may sign in to Grafana with GitHub (as Admin)."
  type        = string
  default     = "jeneeldumasia"
}

locals {
  sso_admin_logins = [for l in split(",", var.sso_admin_github_logins) : trimspace(l) if trimspace(l) != ""]

  grafana_sso_enabled = var.grafana_github_client_id != "" && length(local.sso_admin_logins) > 0
  argocd_sso_enabled  = var.argocd_github_client_id != "" && length(local.access_emails) > 0

  # Grafana evaluates role_attribute_path against GitHub's /user response.
  # Logins outside the list get no role, and role_attribute_strict refuses them.
  grafana_sso_values = local.grafana_sso_enabled ? [yamlencode({
    grafana = {
      "grafana.ini" = {
        "auth.github" = {
          enabled               = true
          client_id             = var.grafana_github_client_id
          scopes                = "read:user user:email"
          allow_sign_up         = true
          role_attribute_path   = "contains([${join(", ", [for l in local.sso_admin_logins : "'${l}'"])}], login) && 'Admin' || ''"
          role_attribute_strict = true
        }
      }
    }
  })] : []

  argocd_sso_values = local.argocd_sso_enabled ? [yamlencode({
    configs = {
      cm = {
        url = "https://argocd.jeneeldumasia.codes"
        "dex.config" = yamlencode({
          connectors = [{
            type = "github"
            id   = "github"
            name = "GitHub"
            config = {
              clientID     = var.argocd_github_client_id
              clientSecret = "$dex.github.clientSecret"
            }
          }]
        })
      }
      rbac = {
        "policy.default" = ""
        scopes           = "[email]"
        "policy.csv"     = join("\n", [for e in local.access_emails : "g, ${e}, role:admin"])
      }
    }
  })] : []
}
