#!/usr/bin/env pwsh
# ShipZen GKE Deployment Verification Script
# This script performs comprehensive checks on the deployed infrastructure

param(
    [Parameter(Mandatory=$false)]
    [string]$ProjectId = $env:GCP_PROJECT_ID,
    
    [Parameter(Mandatory=$false)]
    [string]$Region = "us-central1",
    
    [Parameter(Mandatory=$false)]
    [string]$ClusterName = "shipzen-cluster"
)

$ErrorActionPreference = "Continue"
$WarningCount = 0
$ErrorCount = 0
$SuccessCount = 0

function Write-Status {
    param(
        [string]$Message,
        [ValidateSet("Success", "Warning", "Error", "Info")]
        [string]$Level = "Info"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    switch ($Level) {
        "Success" { 
            Write-Host "[$timestamp] ✓ $Message" -ForegroundColor Green
            $script:SuccessCount++
        }
        "Warning" { 
            Write-Host "[$timestamp] ⚠ $Message" -ForegroundColor Yellow
            $script:WarningCount++
        }
        "Error" { 
            Write-Host "[$timestamp] ✗ $Message" -ForegroundColor Red
            $script:ErrorCount++
        }
        "Info" { 
            Write-Host "[$timestamp] ℹ $Message" -ForegroundColor Cyan
        }
    }
}

function Write-SectionHeader {
    param([string]$Title)
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Magenta
    Write-Host " $Title" -ForegroundColor Magenta
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Magenta
    Write-Host ""
}

Write-SectionHeader "ShipZen GKE Deployment Verification"

# ============================================================================
# 1. Check GCP Authentication and Project
# ============================================================================
Write-SectionHeader "1. GCP Authentication & Configuration"

$account = gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null
if ($account) {
    Write-Status "Authenticated as: $account" -Level Success
} else {
    Write-Status "Not authenticated to GCP. Run: gcloud auth login" -Level Error
    exit 1
}

if ([string]::IsNullOrEmpty($ProjectId)) {
    $ProjectId = gcloud config get-value project 2>$null
}

if ([string]::IsNullOrEmpty($ProjectId)) {
    Write-Status "No GCP project configured" -Level Error
    exit 1
} else {
    gcloud config set project $ProjectId 2>&1 | Out-Null
    Write-Status "Project: $ProjectId" -Level Success
}

# ============================================================================
# 2. Check GKE Cluster
# ============================================================================
Write-SectionHeader "2. GKE Cluster Status"

$clusterStatus = gcloud container clusters describe $ClusterName --region=$Region --format="value(status)" 2>$null
if ($clusterStatus -eq "RUNNING") {
    Write-Status "Cluster '$ClusterName' is RUNNING" -Level Success
    
    # Get cluster credentials
    gcloud container clusters get-credentials $ClusterName --region=$Region --project=$ProjectId 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Cluster credentials configured" -Level Success
    } else {
        Write-Status "Failed to configure cluster credentials" -Level Error
    }
} else {
    Write-Status "Cluster is not running. Status: $clusterStatus" -Level Error
    exit 1
}

# Check kubectl access
$nodes = kubectl get nodes --no-headers 2>$null
if ($LASTEXITCODE -eq 0) {
    $nodeCount = ($nodes | Measure-Object -Line).Lines
    Write-Status "Cluster has $nodeCount node(s)" -Level Success
} else {
    Write-Status "Cannot access cluster via kubectl" -Level Error
    exit 1
}

# ============================================================================
# 3. Check Critical Namespaces
# ============================================================================
Write-SectionHeader "3. Namespace Validation"

$requiredNamespaces = @(
    "argocd",
    "shipzen-system",
    "shipzen-build",
    "keda",
    "external-secrets",
    "envoy-gateway-system",
    "observability"
)

foreach ($ns in $requiredNamespaces) {
    $exists = kubectl get namespace $ns 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Namespace '$ns' exists" -Level Success
    } else {
        Write-Status "Namespace '$ns' not found" -Level Error
    }
}

# ============================================================================
# 4. Check Core Platform Pods
# ============================================================================
Write-SectionHeader "4. Core Platform Components"

$criticalDeployments = @{
    "argocd" = @("argocd-server", "argocd-repo-server", "argocd-application-controller")
    "shipzen-system" = @("shipzen-api", "shipzen-controller", "shipzen-worker", "postgres-postgresql", "redis-master")
    "keda" = @("keda-operator")
    "external-secrets" = @("external-secrets", "external-secrets-webhook")
    "envoy-gateway-system" = @("envoy-gateway")
    "observability" = @("kube-prometheus-stack-operator", "prometheus-kube-prometheus-prometheus", "alertmanager-kube-prometheus-alertmanager")
}

foreach ($ns in $criticalDeployments.Keys) {
    foreach ($deployment in $criticalDeployments[$ns]) {
        $ready = kubectl get deployment $deployment -n $ns --no-headers 2>$null | ForEach-Object {
            $parts = $_ -split '\s+'
            if ($parts.Count -ge 2) {
                $readyReplicas = $parts[1] -split '/'
                if ($readyReplicas.Count -eq 2 -and $readyReplicas[0] -eq $readyReplicas[1] -and $readyReplicas[0] -ne "0") {
                    $true
                } else {
                    $false
                }
            } else {
                $false
            }
        }
        
        if ($ready) {
            Write-Status "$ns/$deployment is ready" -Level Success
        } else {
            # Check if it's a StatefulSet instead
            $stReady = kubectl get statefulset $deployment -n $ns --no-headers 2>$null | ForEach-Object {
                $parts = $_ -split '\s+'
                if ($parts.Count -ge 2) {
                    $readyReplicas = $parts[1] -split '/'
                    if ($readyReplicas.Count -eq 2 -and $readyReplicas[0] -eq $readyReplicas[1] -and $readyReplicas[0] -ne "0") {
                        $true
                    } else {
                        $false
                    }
                } else {
                    $false
                }
            }
            
            if ($stReady) {
                Write-Status "$ns/$deployment (StatefulSet) is ready" -Level Success
            } else {
                Write-Status "$ns/$deployment is not ready or not found" -Level Warning
            }
        }
    }
}

# ============================================================================
# 5. Check ArgoCD Applications
# ============================================================================
Write-SectionHeader "5. ArgoCD Application Status"

$argoApps = kubectl get applications -n argocd --no-headers 2>$null
if ($LASTEXITCODE -eq 0) {
    $argoApps | ForEach-Object {
        $parts = $_ -split '\s+'
        $name = $parts[0]
        $syncStatus = $parts[1]
        $healthStatus = $parts[2]
        
        if ($syncStatus -eq "Synced" -and $healthStatus -eq "Healthy") {
            Write-Status "ArgoCD App '$name' is $syncStatus and $healthStatus" -Level Success
        } elseif ($syncStatus -eq "Synced" -or $healthStatus -match "Progressing|Degraded") {
            Write-Status "ArgoCD App '$name' is $syncStatus and $healthStatus" -Level Warning
        } else {
            Write-Status "ArgoCD App '$name' is $syncStatus and $healthStatus" -Level Error
        }
    }
} else {
    Write-Status "Cannot retrieve ArgoCD applications" -Level Warning
}

# ============================================================================
# 6. Check External Secrets
# ============================================================================
Write-SectionHeader "6. External Secrets Sync Status"

$clusterSecretStore = kubectl get clustersecretstore gcp-secret-manager 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Status "ClusterSecretStore 'gcp-secret-manager' exists" -Level Success
} else {
    Write-Status "ClusterSecretStore 'gcp-secret-manager' not found" -Level Error
}

$externalSecrets = kubectl get externalsecrets -A --no-headers 2>$null
if ($LASTEXITCODE -eq 0 -and $externalSecrets) {
    $externalSecrets | ForEach-Object {
        $parts = $_ -split '\s+'
        $ns = $parts[0]
        $name = $parts[1]
        $status = $parts[2]
        
        if ($status -match "SecretSynced") {
            Write-Status "ExternalSecret $ns/$name is synced" -Level Success
        } else {
            Write-Status "ExternalSecret $ns/$name status: $status" -Level Warning
        }
    }
} else {
    Write-Status "No ExternalSecrets found or cannot retrieve" -Level Warning
}

# ============================================================================
# 7. Check Artifact Registry and GCS
# ============================================================================
Write-SectionHeader "7. GCP Resources"

# Check Artifact Registry
$garRepos = gcloud artifacts repositories list --location=$Region --format="value(name)" 2>$null
if ($garRepos -match "shipzen-builds" -and $garRepos -match "shipzen-platform") {
    Write-Status "Artifact Registry repositories exist" -Level Success
} else {
    Write-Status "Artifact Registry repositories missing" -Level Error
}

# Check GCS Bucket
$gcsBuckets = gcloud storage buckets list --format="value(name)" 2>$null
$buildLogsBucket = $gcsBuckets | Where-Object { $_ -match "shipzen-build-logs" }
if ($buildLogsBucket) {
    Write-Status "GCS build logs bucket exists: $buildLogsBucket" -Level Success
} else {
    Write-Status "GCS build logs bucket not found" -Level Warning
}

# ============================================================================
# 8. Check Load Balancer and Networking
# ============================================================================
Write-SectionHeader "8. Load Balancer & Networking"

$lbServices = kubectl get svc -A -o json 2>$null | ConvertFrom-Json
if ($lbServices) {
    $lbFound = $false
    foreach ($svc in $lbServices.items) {
        if ($svc.spec.type -eq "LoadBalancer") {
            $lbIP = $svc.status.loadBalancer.ingress[0].ip
            if ($lbIP) {
                Write-Status "LoadBalancer found: $($svc.metadata.name) in $($svc.metadata.namespace) - IP: $lbIP" -Level Success
                $lbFound = $true
            }
        }
    }
    
    if (-not $lbFound) {
        Write-Status "No LoadBalancer service with external IP found" -Level Warning
    }
} else {
    Write-Status "Cannot retrieve services" -Level Warning
}

# Check Gateway
$gateway = kubectl get gateway shipzen-gateway -n shipzen-system 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Status "Gateway 'shipzen-gateway' exists" -Level Success
} else {
    Write-Status "Gateway 'shipzen-gateway' not found" -Level Warning
}

# ============================================================================
# 9. Check for Failed Pods
# ============================================================================
Write-SectionHeader "9. Pod Health Check"

$failedPods = kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>$null
if ($failedPods) {
    $failedPods | ForEach-Object {
        $parts = $_ -split '\s+'
        $ns = $parts[0]
        $name = $parts[1]
        $status = $parts[3]
        Write-Status "Pod $ns/$name is in state: $status" -Level Warning
    }
} else {
    Write-Status "All pods are Running or Succeeded" -Level Success
}

# ============================================================================
# 10. Check Database Connectivity
# ============================================================================
Write-SectionHeader "10. Database Connectivity"

$dbSecret = kubectl get secret shipzen-db-credentials -n shipzen-system 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Status "Database credentials secret exists" -Level Success
} else {
    Write-Status "Database credentials secret not found" -Level Error
}

# Check if postgres is accessible
$pgPods = kubectl get pods -n shipzen-system -l app.kubernetes.io/name=postgresql --no-headers 2>$null
if ($pgPods) {
    Write-Status "PostgreSQL pods found" -Level Success
} else {
    Write-Status "PostgreSQL pods not found (may be using Cloud SQL)" -Level Info
}

# ============================================================================
# Summary
# ============================================================================
Write-SectionHeader "Verification Summary"

Write-Host ""
Write-Host "Results:" -ForegroundColor White
Write-Host "  ✓ Successful checks: $SuccessCount" -ForegroundColor Green
Write-Host "  ⚠ Warnings: $WarningCount" -ForegroundColor Yellow
Write-Host "  ✗ Errors: $ErrorCount" -ForegroundColor Red
Write-Host ""

if ($ErrorCount -eq 0 -and $WarningCount -eq 0) {
    Write-Host "🎉 All checks passed! Your ShipZen deployment is healthy." -ForegroundColor Green
    exit 0
} elseif ($ErrorCount -eq 0) {
    Write-Host "✅ Deployment is functional with $WarningCount warning(s)." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "❌ Deployment has $ErrorCount critical error(s) that need attention." -ForegroundColor Red
    exit 1
}
