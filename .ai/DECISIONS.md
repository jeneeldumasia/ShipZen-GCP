# Architectural Decisions - ShipZen-GCP

## Cloud Platform: AWS → GCP
- **Decision**: Migrate from AWS EKS to GCP GKE
- **Reason**: Cluster entered ERROR state (GCE_STOCKOUT), immutable config required destroy/recreate, opportunity to cut costs
- **Cost**: ~$121/month (was ~$300/month on AWS with 3 zones)

## Single Zone for Development
- **Decision**: us-central1-a only
- **Reason**: Save ~$179/month vs 3-zone setup
- **Revert**: Set `node_locations = ["us-central1-a","us-central1-b","us-central1-c"]` in terraform/main.tf

## GitHub App Authentication (No PATs)
- **Decision**: ArgoCD uses GitHub App for private repo access
- **Reason**: Company policy against PATs (long-term access risk)
- **Secret**: `github-app-shipzen` in argocd namespace, label `repo-creds`
- **Variables**: SHIPZEN_GITHUB_APP_ID, SHIPZEN_APP_INSTALLATION_ID, SHIPZEN_GITHUB_APP_PRIVATE_KEY

## Manual Workflow Execution Only
- **Decision**: No auto-deploy on git push
- **Reason**: User preference for manual control, prevents accidental deploys
- **Workflows**: apply-only.yaml (normal updates), destroy-and-deploy.yaml (nuclear), destroy.yaml (teardown)

## Auto-Destroy Every 6 Hours
- **Decision**: destroy.yaml runs on cron `0 */6 * * *`
- **Reason**: Dev environment, prevent runaway GCP costs if forgotten
- **Override**: Cancel the workflow manually to keep infra alive

## Terraform State in HCP Terraform
- **Decision**: Terraform Cloud backend
- **Org**: jeneel-shipzen, **Workspace**: ShipZen-GCP
- **Rule**: Never run `terraform apply` locally

## Node Pool OAuth Scopes
- **Decision**: `https://www.googleapis.com/auth/cloud-platform` on node pool
- **Reason**: GKE nodes need this scope to pull images from Artifact Registry
- **Note**: Adding this scope required node pool recreation (rolling drain)

## ESO Webhook Wait Strategy
- **Decision**: Wait for ESO webhook pod `Ready` before applying ClusterSecretStore
- **Reason**: Node drain kills ESO pods; CRD exists but webhook unreachable causes 10-retry failure
- **Implementation**: `kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=external-secrets-webhook`

## Destroy Pipeline: Active Deletion Not Passive Wait
- **Decision**: destroy.yaml actively deletes GKE-owned GCP resources (firewalls, forwarding rules, backends, health checks, target pools)
- **Reason**: GKE creates these outside Terraform state; terraform destroy fails with "network in use" if they exist
- **Phase order**: k8s drain → GCP artifact deletion → Cloudflare DNS → terraform destroy

## GitOps Teardown via ArgoCD
- **Decision**: Before terraform destroy, switch ArgoCD app to `infra/teardown` path to prune runtime resources
- **Reason**: Lets GKE clean up LoadBalancer GCP resources before cluster is deleted
- **Teardown path**: infra/teardown/kustomization.yaml (only keeps namespaces)

## Append-Only Audit Logs
- **Decision**: PostgreSQL trigger blocks UPDATE/DELETE on audit_logs
- **Reason**: Security compliance
- **Do not remove**: `trg_audit_logs_append_only` trigger in schema.sql

## Kyverno Policy Enforcement
- **Decision**: Strict pod security on tenant namespaces, PolicyExceptions for system components
- **Reason**: Multi-tenant isolation
- **Do not**: Add broad namespace exclusions; use PolicyException instead

## ExternalDNS for Cloudflare
- **Decision**: ExternalDNS operator reads gateway annotations and updates Cloudflare DNS automatically
- **Reason**: Eliminates manual DNS update step after LoadBalancer provisioning
- **Config**: txtOwnerId=shipzen-cluster, domain=jeneeldumasia.codes
