# ShipZen-GCP Task Tracker

## Current (Do This Next)
- [ ] **Run `apply-only.yaml`** to fix pod image pull errors and get site live
  - URL: https://github.com/jeneeldumasia/ShipZen-GCP/actions/workflows/apply-only.yaml
  - Expected outcome: all pods Running, LoadBalancer provisioned, DNS updated

## Blocked On
- All remaining tasks blocked until `apply-only.yaml` succeeds and pods are Running

## After apply-only.yaml Succeeds
- [ ] Verify all pods Running: `kubectl get pods -n shipzen-system`
- [ ] Verify LoadBalancer IP: `kubectl get svc -A | grep LoadBalancer`
- [ ] Verify site accessible: https://shipzen.jeneeldumasia.codes
- [ ] Verify ArgoCD UI: https://argocd.jeneeldumasia.codes
- [ ] Verify Grafana: https://grafana.jeneeldumasia.codes
- [ ] Test end-to-end: connect a GitHub repo via UI, trigger a build

## Completed
- ✅ AWS → GCP migration (EKS, ECR, S3, Secrets)
- ✅ Cost optimization (3 zones → 1 zone, saves ~$179/month)
- ✅ GitHub App auth for ArgoCD (no PAT)
- ✅ Build workflow fixed (correct GAR path)
- ✅ All 4 images built and pushed to GAR (sha-8fc21f6)
- ✅ Node pool oauth_scopes added (fixes 403 on GAR image pull)
- ✅ ESO webhook wait logic added (fixes ClusterSecretStore timeout)
- ✅ destroy.yaml rewritten (4-phase teardown, fixes VPC deletion failure)
- ✅ apply-only.yaml merged with all deploy.yaml steps (secrets, DNS, TLS, webhooks)
- ✅ ExternalDNS added (Copilot PR merged)

## Backlog
- [ ] Production readiness: 3-zone HA setup
- [ ] Cloud SQL PostgreSQL (replace in-cluster)
- [ ] Memorystore Redis (replace in-cluster)
- [ ] Custom domains for tenant deployments
- [ ] Cost monitoring / billing alerts
- [ ] Update architecture diagrams for GCP
- [ ] Runbook for common operations

## Won't Do
- ~~PAT for GitHub auth~~ (company policy)
- ~~Auto-deploy on git push~~ (user preference, manual only)
- ~~Multi-zone for dev~~ (cost savings)
- ✅ Remove the 'Restart System Pods' button from the admin UI (SystemControls.tsx) because ArgoCD reverts the deployment patches.