# ── Bastion Host for Kubectl Access ───────────────────────────────────────────

# Allow SSH via IAP (Identity-Aware Proxy)
resource "google_compute_firewall" "allow_ssh_iap" {
  name    = "allow-ssh-iap"
  network = google_compute_network.vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"] # Google IAP IP range
  
  target_tags = ["bastion"]
}

resource "google_service_account" "bastion_sa" {
  account_id   = "shipzen-bastion-sa"
  display_name = "ShipZen Bastion Service Account"
}

# Allow bastion to access GKE cluster
resource "google_project_iam_member" "bastion_cluster_admin" {
  project = var.gcp_project
  role    = "roles/container.admin"
  member  = "serviceAccount:${google_service_account.bastion_sa.email}"
}

resource "google_compute_instance" "bastion" {
  name         = "shipzen-bastion"
  machine_type = "e2-micro"
  zone         = "${var.gcp_region}-a" # Aligns with the single zone cluster

  tags = ["bastion"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 20
    }
  }

  network_interface {
    network    = google_compute_network.vpc.name
    subnetwork = google_compute_subnetwork.subnet.name
    # No access_config block means it won't have a public IP, increasing security.
    # We will connect using IAP.
  }

  service_account {
    email  = google_service_account.bastion_sa.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    sudo apt-get update
    sudo apt-get install -y kubectl google-cloud-sdk-gke-gcloud-auth-plugin git jq
  EOT
}
