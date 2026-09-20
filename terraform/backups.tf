resource "google_storage_bucket" "velero_backups" {
  name          = "${var.gcp_project}-velero-backups"
  location      = var.gcp_region
  force_destroy = true

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_service_account" "velero_sa" {
  account_id   = "velero-backup-sa"
  display_name = "Service Account for Velero Backups"
}

resource "google_storage_bucket_iam_member" "velero_sa_object_admin" {
  bucket = google_storage_bucket.velero_backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.velero_sa.email}"
}

# Workload Identity binding for Velero
resource "google_service_account_iam_member" "velero_workload_identity" {
  service_account_id = google_service_account.velero_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.gcp_project}.svc.id.goog[velero/velero]"
}
