#!/usr/bin/env pwsh
# ShipZen GKE Cluster Access Fix Script
# This script diagnoses and fixes cluster authentication issues

param(
    [Parameter(Mandatory=$false)]
    [string]$ProjectId = $env:GCP_PROJECT_ID,
    
    [Parameter(Mandatory=$false)]
    [string]$Region = "us-central1",
    
    [Parameter(Mandatory=$false)]
    [string]$ClusterName = "shipzen-cluster"
)

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "ShipZen GKE Cluster Access Fixer" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Check if gcloud is installed
Write-Host "[1/7] Checking gcloud CLI installation..." -ForegroundColor Yellow
try {
    $gcloudVersion = gcloud version 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud not found"
    }
    Write-Host "✓ gcloud CLI is installed" -ForegroundColor Green
} catch {
    Write-Host "✗ gcloud CLI is not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install gcloud CLI:" -ForegroundColor Yellow
    Write-Host "  Windows: https://cloud.google.com/sdk/docs/install#windows" -ForegroundColor Cyan
    Write-Host "  Or use: choco install gcloudsdk" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

# Check authentication
Write-Host ""
Write-Host "[2/7] Checking GCP authentication..." -ForegroundColor Yellow
try {
    $account = gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null
    if ([string]::IsNullOrEmpty($account)) {
        Write-Host "✗ Not authenticated to GCP" -ForegroundColor Red
        Write-Host ""
        Write-Host "Running: gcloud auth login" -ForegroundColor Yellow
        gcloud auth login
        if ($LASTEXITCODE -ne 0) {
            throw "Authentication failed"
        }
    } else {
        Write-Host "✓ Authenticated as: $account" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ Authentication failed: $_" -ForegroundColor Red
    exit 1
}

# Check/Set project
Write-Host ""
Write-Host "[3/7] Checking GCP project configuration..." -ForegroundColor Yellow
if ([string]::IsNullOrEmpty($ProjectId)) {
    $currentProject = gcloud config get-value project 2>$null
    if ([string]::IsNullOrEmpty($currentProject)) {
        Write-Host "✗ No project configured" -ForegroundColor Red
        Write-Host ""
        Write-Host "Please specify project ID:" -ForegroundColor Yellow
        Write-Host "  .\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID" -ForegroundColor Cyan
        exit 1
    }
    $ProjectId = $currentProject
}

Write-Host "Setting project to: $ProjectId" -ForegroundColor Cyan
gcloud config set project $ProjectId 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Project set to: $ProjectId" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to set project" -ForegroundColor Red
    exit 1
}

# Install gke-gcloud-auth-plugin if needed
Write-Host ""
Write-Host "[4/7] Checking gke-gcloud-auth-plugin..." -ForegroundColor Yellow
try {
    $pluginCheck = gke-gcloud-auth-plugin --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing gke-gcloud-auth-plugin..." -ForegroundColor Yellow
        gcloud components install gke-gcloud-auth-plugin --quiet
    }
    Write-Host "✓ gke-gcloud-auth-plugin is installed" -ForegroundColor Green
} catch {
    Write-Host "⚠ Could not verify plugin, but continuing..." -ForegroundColor Yellow
}

# Check if cluster exists
Write-Host ""
Write-Host "[5/7] Checking if cluster exists..." -ForegroundColor Yellow
$clusterExists = gcloud container clusters list --filter="name=$ClusterName" --format="value(name)" --region=$Region 2>$null
if ([string]::IsNullOrEmpty($clusterExists)) {
    Write-Host "✗ Cluster '$ClusterName' not found in region '$Region'" -ForegroundColor Red
    Write-Host ""
    Write-Host "Available clusters:" -ForegroundColor Yellow
    gcloud container clusters list --format="table(name,location,status)"
    Write-Host ""
    Write-Host "The cluster may need to be created. Check GitHub Actions deployment logs." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "✓ Cluster '$ClusterName' exists" -ForegroundColor Green
}

# Check cluster status
Write-Host ""
Write-Host "[6/7] Checking cluster status..." -ForegroundColor Yellow
$clusterStatus = gcloud container clusters describe $ClusterName --region=$Region --format="value(status)" 2>$null
if ($clusterStatus -ne "RUNNING") {
    Write-Host "✗ Cluster is not running. Status: $clusterStatus" -ForegroundColor Red
    Write-Host ""
    Write-Host "Cluster details:" -ForegroundColor Yellow
    gcloud container clusters describe $ClusterName --region=$Region
    exit 1
} else {
    Write-Host "✓ Cluster is RUNNING" -ForegroundColor Green
}

# Get credentials
Write-Host ""
Write-Host "[7/7] Configuring kubectl credentials..." -ForegroundColor Yellow
try {
    gcloud container clusters get-credentials $ClusterName --region=$Region --project=$ProjectId
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to get credentials"
    }
    Write-Host "✓ Credentials configured successfully" -ForegroundColor Green
} catch {
    Write-Host "✗ Failed to configure credentials: $_" -ForegroundColor Red
    exit 1
}

# Verify kubectl access
Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Verification Tests" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Testing kubectl access..." -ForegroundColor Yellow
try {
    $nodes = kubectl get nodes 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ kubectl cannot access cluster" -ForegroundColor Red
        Write-Host $nodes
        exit 1
    }
    Write-Host "✓ kubectl access successful" -ForegroundColor Green
    Write-Host ""
    Write-Host "Cluster Nodes:" -ForegroundColor Cyan
    kubectl get nodes -o wide
} catch {
    Write-Host "✗ kubectl test failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Checking critical namespaces..." -ForegroundColor Yellow
$namespaces = @("argocd", "shipzen-system", "shipzen-build", "keda", "external-secrets", "observability")
foreach ($ns in $namespaces) {
    $exists = kubectl get namespace $ns 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Namespace '$ns' exists" -ForegroundColor Green
    } else {
        Write-Host "⚠ Namespace '$ns' not found (may not be deployed yet)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Checking pod status..." -ForegroundColor Yellow
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>$null | Select-Object -First 20
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Pod status check complete" -ForegroundColor Green
}

Write-Host ""
Write-Host "=====================================" -ForegroundColor Green
Write-Host "Cluster Access Fixed Successfully!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Green
Write-Host ""
Write-Host "You can now run kubectl commands:" -ForegroundColor Cyan
Write-Host "  kubectl get pods -A" -ForegroundColor White
Write-Host "  kubectl get applications -n argocd" -ForegroundColor White
Write-Host "  kubectl logs -n shipzen-system deployment/shipzen-api" -ForegroundColor White
Write-Host ""
