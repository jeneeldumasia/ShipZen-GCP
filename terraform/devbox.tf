# ── Persistent DevBox for Antigravity IDE & Cluster Debugging ───────────────

# Allow SSH via IAP (Identity-Aware Proxy)
resource "google_compute_firewall" "allow_ssh_iap_devbox" {
  name    = "allow-ssh-iap-devbox"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"] # Google IAP IP range
  
  target_tags = ["devbox"]
}

resource "google_service_account" "devbox_sa" {
  account_id   = "shipzen-devbox-sa"
  display_name = "ShipZen DevBox Service Account"
}

# Allow devbox to manage the GKE cluster
resource "google_project_iam_member" "devbox_cluster_admin" {
  project = var.gcp_project
  role    = "roles/container.admin"
  member  = "serviceAccount:${google_service_account.devbox_sa.email}"
}

# Allow devbox to pull/push from Artifact Registry
resource "google_project_iam_member" "devbox_ar_admin" {
  project = var.gcp_project
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.devbox_sa.email}"
}

resource "google_compute_instance" "devbox" {
  name         = "shipzen-devbox"
  machine_type = "e2-medium" # 2 vCPU, 4GB RAM to balance cost and IDE usage
  zone         = "${var.gcp_region}-a"

  tags = ["devbox"]

  # PREVENT ACCIDENTAL DESTRUCTION
  deletion_protection = true

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 50 # 50GB persistent disk
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"
    # No public IP assigned to maximize security. Access happens securely via IAP.
  }

  service_account {
    email  = google_service_account.devbox_sa.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    sudo apt-get update
    
    # Install core dev tools, kubectl, python, and GKE plugin
    sudo apt-get install -y \
      git jq curl wget tmux \
      apt-transport-https ca-certificates gnupg lsb-release \
      kubectl google-cloud-sdk-gke-gcloud-auth-plugin \
      python3 python3-pip python3-venv xvfb libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libgbm1 libasound2

    # Install Docker
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Allow non-root docker access globally (since it's a private devbox)
    sudo chmod 666 /var/run/docker.sock
  EOT
}
