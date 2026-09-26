terraform {
  cloud {
    organization = "jeneel-shipzen"
    workspaces {
      name = "ShipZen-GCP-DevBox"
    }
  }
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "gcp_project" {
  type = string
}

variable "gcp_region" {
  type    = string
  default = "us-central1"
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region
}

# ── Persistent DevBox for Antigravity IDE & Cluster Debugging ───────────────

resource "google_compute_firewall" "allow_ssh_iap_devbox" {
  name    = "allow-ssh-iap-devbox"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"] # Google IAP IP range
  target_tags   = ["devbox"]
}

resource "google_service_account" "devbox_sa" {
  account_id   = "shipzen-devbox-sa"
  display_name = "ShipZen DevBox Service Account"
}

resource "google_project_iam_member" "devbox_cluster_admin" {
  project = var.gcp_project
  role    = "roles/container.admin"
  member  = "serviceAccount:${google_service_account.devbox_sa.email}"
}

resource "google_project_iam_member" "devbox_ar_admin" {
  project = var.gcp_project
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.devbox_sa.email}"
}

resource "google_compute_instance" "devbox" {
  name         = "shipzen-devbox"
  machine_type = "e2-medium"
  zone         = "${var.gcp_region}-a"

  tags = ["devbox"]

  # PREVENT ACCIDENTAL DESTRUCTION
  deletion_protection = true

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 50
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"
    access_config {
      # Ephemeral public IP to allow outbound internet access for apt-get downloads.
      # (Ingress is still 100% blocked by GCP default firewall rules).
    }
  }

  service_account {
    email  = google_service_account.devbox_sa.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    sudo apt-get update
    sudo apt-get install -y git jq curl wget tmux apt-transport-https ca-certificates gnupg lsb-release kubectl google-cloud-cli-gke-gcloud-auth-plugin python3 python3-pip python3-venv xvfb libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libgbm1 libasound2
    
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    sudo chmod 666 /var/run/docker.sock
    
    # ── Install Remote Desktop Environment (XFCE + XRDP)
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y xfce4 xfce4-goodies xrdp
    sudo systemctl enable xrdp
    sudo adduser xrdp ssl-cert
    echo "xfce4-session" | sudo tee /etc/skel/.xsession
    
    # ── Install Browser-based IDE (code-server)
    # Using -4 to force IPv4 and prevent IPv6 connection timeouts
    curl -fsSL -4 https://code-server.dev/install.sh | sh
  EOT
}
