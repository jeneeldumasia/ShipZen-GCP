#!/usr/bin/env pwsh
# Fix GKE cluster GCE_STOCKOUT error by recreating with better zone/machine type

param(
    [Parameter(Mandatory=$false)]
    [string]$ProjectId = "project-ce3f7c39-eceb-4221-a76",
    
    [Parameter(Mandatory=$false)]
    [string]$Region = "us-central1",
    
    [Parameter(Mandatory=$false)]
    [string]$ClusterName = "shipzen-cluster"
)

# Add gcloud to PATH
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"

Write-Host "======================================" -ForegroundColor Red
Write-Host "GKE Cluster Stockout Fix" -ForegroundColor Red  
Write-Host "======================================" -ForegroundColor Red
Write-Host ""

Write-Host "Your cluster is in ERROR state due to GCE_STOCKOUT" -ForegroundColor Yellow
Write-Host "This means Google Cloud doesn't have enough capacity in the requested zone." -ForegroundColor Yellow
Write-Host ""

Write-Host "Current cluster status:" -ForegroundColor Cyan
gcloud container clusters describe $ClusterName --region=$Region --project=$ProjectId --format="table(name,location,status,currentMasterVersion,currentNodeVersion,currentNodeCount)"

Write-Host ""
Write-Host "OPTIONS:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. DELETE and RECREATE cluster (Recommended)" -ForegroundColor Green
Write-Host "   - Uses terraform to create fresh cluster with correct machine type (n2-standard-8)"
Write-Host "   - Fixes zone selection and configuration"
Write-Host "   - ⚠️  WARNING: This will destroy all existing workloads!" -ForegroundColor Yellow
Write-Host ""
Write-Host "2. Try to RESIZE node pool to 0, then back up (May not work)" -ForegroundColor Yellow
Write-Host "   - Attempts to force GKE to reallocate in available zones"
Write-Host "   - Lower success rate with stockout errors"
Write-Host ""
Write-Host "3. CANCEL and investigate manually" -ForegroundColor White
Write-Host ""

$choice = Read-Host "Enter choice (1, 2, or 3)"

switch ($choice) {
    "1" {
        Write-Host ""
        Write-Host "⚠️  DESTRUCTIVE OPERATION WARNING ⚠️" -ForegroundColor Red
        Write-Host "This will DELETE the cluster and ALL data in it!" -ForegroundColor Red
        Write-Host ""
        Write-Host "Type 'YES' to confirm cluster deletion:" -ForegroundColor Yellow
        $confirm = Read-Host
        
        if ($confirm -eq "YES") {
            Write-Host ""
            Write-Host "Deleting cluster..." -ForegroundColor Yellow
            gcloud container clusters delete $ClusterName --region=$Region --project=$ProjectId --quiet
            
            Write-Host ""
            Write-Host "Cluster deleted. Now run terraform to recreate:" -ForegroundColor Green
            Write-Host ""
            Write-Host "  cd c:\Project\ShipZen-GCP\terraform" -ForegroundColor Cyan
            Write-Host "  terraform init" -ForegroundColor Cyan
            Write-Host "  terraform apply" -ForegroundColor Cyan
            Write-Host ""
        } else {
            Write-Host "Deletion cancelled." -ForegroundColor Yellow
        }
    }
    
    "2" {
        Write-Host ""
        Write-Host "Attempting node pool resize..." -ForegroundColor Yellow
        
        # Get the default node pool name
        $nodePoolName = gcloud container node-pools list --cluster=$ClusterName --region=$Region --project=$ProjectId --format="value(name)" | Select-Object -First 1
        
        Write-Host "Resizing node pool '$nodePoolName' to 0..." -ForegroundColor Cyan
        gcloud container clusters resize $ClusterName --region=$Region --project=$ProjectId --node-pool=$nodePoolName --num-nodes=0 --quiet
        
        Write-Host "Waiting 30 seconds..." -ForegroundColor Cyan
        Start-Sleep -Seconds 30
        
        Write-Host "Resizing node pool back to 1..." -ForegroundColor Cyan
        gcloud container clusters resize $ClusterName --region=$Region --project=$ProjectId --node-pool=$nodePoolName --num-nodes=1 --quiet
        
        Write-Host ""
        Write-Host "Resize complete. Check cluster status:" -ForegroundColor Green
        Write-Host "  gcloud container clusters list --project $ProjectId" -ForegroundColor Cyan
    }
    
    "3" {
        Write-Host ""
        Write-Host "Operation cancelled. To investigate:" -ForegroundColor Yellow
        Write-Host "  gcloud container clusters describe $ClusterName --region=$Region --project=$ProjectId" -ForegroundColor Cyan
    }
    
    default {
        Write-Host "Invalid choice. Exiting." -ForegroundColor Red
    }
}
