# ShipZen GCP Migration Summary

## Overview
This document summarizes all changes made to migrate ShipZen from AWS to Google Cloud Platform (GCP).

## Changes Made

### 1. Authentication & Access Control

**Before (AWS):**
- AWS IAM OIDC Provider
- IAM Roles with `AssumeRoleWithWebIdentity`
- Static IAM credentials for services

**After (GCP):**
- GCP Workload Identity Federation for GitHub Actions
- Service Accounts with Workload Identity bindings
- Native GKE Workload Identity for pods

**Files Changed:**
- `docs/GCP_SETUP_GUIDE.md` - Complete rewrite with GCP instructions
- `.github/workflows/deploy.yaml` - Uses GCP authentication
- `terraform/main.tf` - Workload Identity configuration

### 2. Container Registry

**Before (AWS):**
- Amazon Elastic Container Registry (ECR)
- ECR authentication tokens
- `dkr.ecr.{region}.amazonaws.com`

**After (GCP):**
- Google Artifact Registry (GAR)
- Workload Identity-based authentication
- `{region}-docker.pkg.dev/{project}/{repository}`

**Files Changed:**
- `controller/main.py` - Changed `ECR_REGISTRY` → `GAR_REGISTRY`
- `controller/templates/tenant.yaml.j2` - GCRAccessToken instead of ECRAuthorizationToken
- `controller/templates/app-deployment.yaml.j2` - `gar-pull-secret` instead of `ecr-pull-secret`
- `infra/controller/deployment.yaml` - GAR environment variables
- `infra/api/deployment.yaml` - GAR environment variables
- `terraform/artifact-registry-secrets.tf` - New file for GAR configuration

### 3. Object Storage

**Before (AWS):**
- Amazon S3
- `S3_LOG_BUCKET` environment variable
- AWS SDK for Python (boto3)

**After (GCP):**
- Google Cloud Storage (GCS)
- `GCS_LOG_BUCKET` environment variable
- Google Cloud SDK for Python

**Files Changed:**
- `infra/worker/deployment.yaml` - `GCS_LOG_BUCKET` environment variable
- `terraform/main.tf` - `google_storage_bucket` resource
- `terraform/artifact-registry-secrets.tf` - GCS bucket configuration secrets

### 4. Secret Management

**Before (AWS):**
- AWS Secrets Manager
- ClusterSecretStore with AWS provider
- Secret paths like `shipzen/{project}/`

**After (GCP):**
- GCP Secret Manager
- ClusterSecretStore with `gcpsm` provider
- Secret names like `shipzen-{project}`

**Files Changed:**
- `controller/templates/app-deployment.yaml.j2` - ClusterSecretStore reference
- `infra/system/*.yaml` - All ExternalSecret resources
- `terraform/operators.tf` - ClusterSecretStore configuration

### 5. Kubernetes Cluster

**Before (AWS):**
- Amazon Elastic Kubernetes Service (EKS)
- EKS-specific configurations
- IRSA (IAM Roles for Service Accounts)

**After (GCP):**
- Google Kubernetes Engine (GKE)
- GKE-specific configurations
- Workload Identity

**Files Changed:**
- `terraform/main.tf` - `google_container_cluster` resource
- `terraform/main.tf` - `google_container_node_pool` resource
- `.github/workflows/*.yaml` - `gcloud container clusters get-credentials`

### 6. Infrastructure as Code

**Before (AWS):**
- AWS provider
- `aws_` resource prefixes
- IAM policies and roles

**After (GCP):**
- Google provider
- `google_` resource prefixes
- Service accounts and IAM bindings

**Files Changed:**
- `terraform/main.tf` - Provider and core infrastructure
- `terraform/operators.tf` - Operator deployments
- `terraform/postgres.tf` - Database options (Cloud SQL)
- `terraform/redis.tf` - Redis with GCP Secret Manager
- `terraform/security.tf` - GKE security configurations
- `terraform/artifact-registry-secrets.tf` - New file
- `terraform/variables.tf` - Variable updates

### 7. Documentation

**Before:**
- Mixed AWS/GCP references
- Outdated setup instructions
- Incorrect authentication flows

**After:**
- Consistent GCP terminology
- Updated setup instructions
- Correct Workload Identity Federation steps

**Files Changed:**
- `docs/GCP_SETUP_GUIDE.md` - Complete rewrite
- `QUICK_START.md` - New troubleshooting guide
- `MIGRATION_SUMMARY.md` - This file

### 8. Scripts & Tooling

**New Files Created:**
- `scripts/fix-cluster-access.ps1` - PowerShell script for GKE authentication
- `scripts/verify-deployment.ps1` - Comprehensive deployment verification
- `QUICK_START.md` - Quick troubleshooting reference

## Configuration Changes Required

### Environment Variables

| Old (AWS) | New (GCP) | Component |
|-----------|-----------|-----------|
| `ECR_REGISTRY` | `GAR_REGISTRY` | Controller |
| `ECR_REPOSITORY_URL` | `GAR_REPOSITORY_URL` | API |
| `S3_LOG_BUCKET` | `GCS_LOG_BUCKET` | Worker |
| `AWS_REGION` | `GCP_REGION` | All |
| - | `GCP_PROJECT` | Controller |

### Kubernetes Secrets

| Secret Name | Old Keys | New Keys | Namespace |
|-------------|----------|----------|-----------|
| `shipzen-ecr-config` | `registry_hostname`, `repository_url` | → `shipzen-gar-config` | shipzen-system |
| `shipzen-s3-config` | `bucket_name` | → `shipzen-gcs-config` | shipzen-system |
| `redis-auth` | `redis-password` | (unchanged) | shipzen-system |
| `shipzen-db-credentials` | `url` | (unchanged) | shipzen-system |

### External Secrets

All `ExternalSecret` resources now reference:
- `secretStoreRef.name: gcp-secret-manager` (was `aws-secrets-manager`)
- `secretStoreRef.kind: ClusterSecretStore` (unchanged)

Secret key format changed:
- AWS: `shipzen/{project_name}/` (path-based)
- GCP: `shipzen-{project_name}` (name-based)

### Workload Identity Bindings

New service accounts with Workload Identity bindings:
1. `shipzen-builder-sa` - Writes to GAR and GCS
2. `shipzen-eso-sa` - Reads from GCP Secret Manager
3. `shipzen-worker-sa` - Creates build jobs
4. `shipzen-api-sa` - (future use)

## Verification Steps

After migration, verify:

1. **Cluster Access:**
   ```powershell
   .\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID
   ```

2. **Infrastructure:**
   ```bash
   gcloud container clusters list
   gcloud artifacts repositories list
   gcloud storage buckets list
   ```

3. **Deployments:**
   ```powershell
   .\scripts\verify-deployment.ps1 -ProjectId YOUR_PROJECT_ID
   ```

4. **Pod Status:**
   ```bash
   kubectl get pods -A
   ```

5. **External Secrets:**
   ```bash
   kubectl get externalsecrets -A
   kubectl get clustersecretstore
   ```

## Breaking Changes

⚠️ **Important:** These changes break compatibility with AWS deployments:

1. **Cannot use AWS ECR** - All container images must be in GCP Artifact Registry
2. **Cannot use AWS Secrets Manager** - All secrets must be in GCP Secret Manager
3. **Cannot use AWS S3** - Build logs must use GCS
4. **Different authentication** - GitHub Actions must use Workload Identity Federation
5. **Different CLI tools** - Must use `gcloud` instead of `aws` CLI

## Rollback Considerations

To rollback to AWS (if needed):
1. Revert all file changes in this migration
2. Restore AWS-specific Terraform state
3. Update GitHub secrets to AWS credentials
4. Push container images back to ECR
5. Migrate secrets back to AWS Secrets Manager

**Note:** This is not recommended. Instead, fix issues in the GCP deployment.

## Cost Implications

### GCP Free Tier Benefits:
- $300 free credits for new accounts
- Always-free GKE cluster (1 zonal cluster)
- 5 GB-months standard storage on Cloud Storage
- 6 Storage API Class A operations per second

### Expected Costs (after free tier):
- **GKE Cluster:** ~$75/month (n2-standard-8 nodes)
- **Artifact Registry:** ~$0.10/GB/month
- **Cloud Storage:** ~$0.02/GB/month
- **Secret Manager:** ~$0.06 per 10,000 accesses
- **Egress:** Varies by region and usage

### Cost Optimization Tips:
1. Use Preemptible/Spot nodes for non-critical workloads
2. Enable GKE Autopilot mode (future enhancement)
3. Use Cloud SQL free tier (db-f1-micro)
4. Set lifecycle policies on GCS buckets (already configured for 30 days)

## Next Steps

1. ✅ Complete migration (all changes documented above)
2. ⏭️ Test end-to-end deployment flow
3. ⏭️ Update CI/CD pipelines for production
4. ⏭️ Set up monitoring and alerting
5. ⏭️ Configure backup and disaster recovery
6. ⏭️ Implement cost monitoring dashboards
7. ⏭️ Document operational procedures

## Support

For issues or questions:
1. Check `QUICK_START.md` for common troubleshooting steps
2. Review `docs/ISSUES_AND_RESOLUTIONS.md` for historical fixes
3. Run `.\scripts\verify-deployment.ps1` for diagnostics
4. Check GitHub Actions workflow logs
5. Review GCP Console for resource status

---

**Migration completed:** January 2025  
**Platform:** Google Cloud Platform (GCP)  
**Primary Region:** us-central1  
**Kubernetes:** Google Kubernetes Engine (GKE)
