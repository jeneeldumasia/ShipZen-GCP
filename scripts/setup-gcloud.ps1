#!/usr/bin/env pwsh
# Setup gcloud CLI in PowerShell session
# This script adds gcloud to PATH and initializes it

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Setting up gcloud CLI" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Define the gcloud installation path
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"

# Check if gcloud exists
if (Test-Path "$gcloudPath\gcloud.cmd") {
    Write-Host "✓ Found gcloud at: $gcloudPath" -ForegroundColor Green
    
    # Add to current session PATH if not already there
    if ($env:Path -notlike "*$gcloudPath*") {
        $env:Path = "$gcloudPath;$env:Path"
        Write-Host "✓ Added gcloud to current session PATH" -ForegroundColor Green
    } else {
        Write-Host "✓ gcloud already in PATH" -ForegroundColor Green
    }
    
    # Add to user PATH permanently
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$gcloudPath*") {
        Write-Host ""
        Write-Host "Do you want to add gcloud to your PATH permanently? (Y/N)" -ForegroundColor Yellow
        $response = Read-Host
        if ($response -eq 'Y' -or $response -eq 'y') {
            [Environment]::SetEnvironmentVariable("Path", "$gcloudPath;$userPath", "User")
            Write-Host "✓ Added gcloud to user PATH permanently" -ForegroundColor Green
            Write-Host "  (You may need to restart PowerShell for this to take effect)" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "Testing gcloud..." -ForegroundColor Cyan
    & "$gcloudPath\gcloud.cmd" version
    
    Write-Host ""
    Write-Host "======================================" -ForegroundColor Green
    Write-Host "gcloud Setup Complete!" -ForegroundColor Green
    Write-Host "======================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "1. Authenticate: gcloud auth login" -ForegroundColor White
    Write-Host "2. Set project: gcloud config set project YOUR_PROJECT_ID" -ForegroundColor White
    Write-Host "3. Fix cluster access: .\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID" -ForegroundColor White
    Write-Host ""
    
} else {
    Write-Host "✗ gcloud not found at expected location" -ForegroundColor Red
    Write-Host "  Expected: $gcloudPath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please install gcloud SDK from:" -ForegroundColor Yellow
    Write-Host "  https://cloud.google.com/sdk/docs/install" -ForegroundColor Cyan
}
