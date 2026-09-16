#!/usr/bin/env pwsh
# Terraform-based cluster recreation script

param(
    [Parameter(Mandatory=$false)]
    [string]$ProjectId = "project-ce3f7c39-eceb-4221-a76",
    
    [Parameter(Mandatory=$false)]
    [string]$Region = "us-central1",
    
    [Parameter(Mandatory=$false)]
    [string]$MachineType = "e2-standard-4"
)

# Setup gcloud in PATH
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "ShipZen Cluster Recreate via Terraform" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project: $ProjectId" -ForegroundColor White
Write-Host "Region: $Region" -ForegroundColor White
Write-Host "Machine Type: $MachineType" -ForegroundColor White
Write-Host ""

# Check if in correct directory
if (-not (Test-Path "terraform\main.tf")) {
    Write-Host "ERROR: Please run this from the ShipZen-GCP root directory" -ForegroundColor Red
    exit 1
}

# Verify authentication
$account = gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null
if (-not $account) {
    Write-Host "ERROR: Not authenticated to GCP" -ForegroundColor Red
    Write-Host "Run: gcloud auth login" -ForegroundColor Yellow
    exit 1
}
Write-Host "??? Authenticated as: $account" -ForegroundColor Green

# Check application default credentials
Write-Host ""
Write-Host "Checking application default credentials..." -ForegroundColor Cyan
$adcCheck = gcloud auth application-default print-access-token 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "??? Application default credentials not set" -ForegroundColor Yellow
    Write-Host "  This is required for Terraform to authenticate" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Run this command:" -ForegroundColor Yellow
    Write-Host "  gcloud auth application-default login" -ForegroundColor Cyan
    Write-Host ""
    $response = Read-Host "Run it now? (Y/N)"
    if ($response -eq 'Y' -or $response -eq 'y') {
        gcloud auth application-default login
    } else {
        Write-Host "Exiting. Please set up ADC first." -ForegroundColor Red
        exit 1
    }
}
Write-Host "??? Application default credentials OK" -ForegroundColor Green

# Navigate to terraform directory
Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "Step 1: Terraform Init" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""
Set-Location terraform

terraform init
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Terraform init failed" -ForegroundColor Red
    exit 1
}

# Show current state
Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "Current Cluster State" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""
gcloud container clusters list --project $ProjectId

Write-Host ""
Write-Host "=============================================" -ForegroundColor Yellow
Write-Host "DESTROY CONFIRMATION" -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "This will:" -ForegroundColor White
Write-Host "  1. Destroy the broken GKE cluster" -ForegroundColor Yellow
Write-Host "  2. Destroy the node pool" -ForegroundColor Yellow
Write-Host "  3. Preserve VPC, Artifact Registry, GCS, Secrets" -ForegroundColor Green
Write-Host ""
Write-Host "Type 'YES' to proceed with targeted destroy:" -ForegroundColor Red
$confirm = Read-Host

if ($confirm -ne "YES") {
    Write-Host "Operation cancelled." -ForegroundColor Yellow
    Set-Location ..
    exit 0
}

# Targeted destroy
Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "Step 2: Destroy Cluster (Targeted)" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

terraform destroy `
    -target=google_container_cluster.primary `
    -target=google_container_node_pool.platform_nodes `
    -var="gcp_project=$ProjectId" `
    -var="gcp_region=$Region" `
    -var="platform_machine_type=$MachineType" `
    -auto-approve

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "??? Terraform destroy had issues. Checking if manual cleanup needed..." -ForegroundColor Yellow
    
    $clusterExists = gcloud container clusters list --filter="name=shipzen-cluster" --project $ProjectId 2>$null
    if ($clusterExists) {
        Write-Host ""
        Write-Host "Cluster still exists. Attempting manual deletion..." -ForegroundColor Yellow
        gcloud container clusters delete shipzen-cluster --region $Region --project $ProjectId --quiet
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Manual deletion also failed" -ForegroundColor Red
            Set-Location ..
            exit 1
        }
    }
}

Write-Host ""
Write-Host "??? Cluster destroyed" -ForegroundColor Green

# Recreate
Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "Step 3: Recreate Infrastructure" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "This will take 15-20 minutes..." -ForegroundColor Yellow
Write-Host ""

terraform apply `
    -var="gcp_project=$ProjectId" `
    -var="gcp_region=$Region" `
    -var="platform_machine_type=$MachineType" `
    -auto-approve

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Terraform apply failed" -ForegroundColor Red
    Set-Location ..
    exit 1
}

Write-Host ""
Write-Host "??? Infrastructure created" -ForegroundColor Green

# Get credentials
Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "Step 4: Configure kubectl" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

gcloud container clusters get-credentials shipzen-cluster --region $Region --project $ProjectId

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to get cluster credentials" -ForegroundColor Red
    Set-Location ..
    exit 1
}

Write-Host ""
Write-Host "??? kubectl configured" -ForegroundColor Green

# Verify
Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "Step 5: Verify Deployment" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

kubectl get nodes
Write-Host ""
kubectl get pods -A

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "Cluster Recreation Complete!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Wait for all pods to start (~5 minutes)" -ForegroundColor White
Write-Host "  2. Run full verification: cd .. ; .\scripts\verify-deployment.ps1" -ForegroundColor White
Write-Host "  3. Check ArgoCD: kubectl get applications -n argocd" -ForegroundColor White
Write-Host ""
Write-Host "Machine type: $MachineType" -ForegroundColor Cyan
$costEstimate = if ($MachineType -like "*n2-standard-4*") { "~`$360" } elseif ($MachineType -like "*e2-standard-4*") { "~`$300" } else { "~`$150-450" }
Write-Host "Estimated cost: 300-360 USD per month for 3 nodes" -ForegroundColor Cyan
Write-Host ""

Set-Location ..

