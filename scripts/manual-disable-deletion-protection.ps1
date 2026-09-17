# Manual script to disable deletion protection on GKE cluster

Write-Host "Disabling deletion protection on shipzen-cluster..." -ForegroundColor Cyan

# Update the cluster directly via gcloud
gcloud container clusters update shipzen-cluster `
  --region us-central1 `
  --no-deletion-protection `
  --project project-ce3f7c39-eceb-4221-a76

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ Deletion protection disabled successfully!" -ForegroundColor Green
    Write-Host "`nYou can now destroy the cluster with:" -ForegroundColor Yellow
    Write-Host "  cd terraform" -ForegroundColor White
    Write-Host "  terraform destroy -auto-approve" -ForegroundColor White
} else {
    Write-Host "`n❌ Failed to disable deletion protection" -ForegroundColor Red
    Write-Host "Error code: $LASTEXITCODE" -ForegroundColor Red
}
