import {
  to = google_compute_network.vpc
  id = "projects/project-ce3f7c39-eceb-4221-a76/global/networks/shipzen-vpc"
}

import {
  to = google_artifact_registry_repository.shipzen_builds
  id = "projects/project-ce3f7c39-eceb-4221-a76/locations/us-central1/repositories/shipzen-builds"
}

import {
  to = google_artifact_registry_repository.platform
  id = "projects/project-ce3f7c39-eceb-4221-a76/locations/us-central1/repositories/shipzen-platform"
}

import {
  to = google_service_account.builder_sa
  id = "projects/project-ce3f7c39-eceb-4221-a76/serviceAccounts/shipzen-builder-sa@project-ce3f7c39-eceb-4221-a76.iam.gserviceaccount.com"
}

import {
  to = google_service_account.eso_sa
  id = "projects/project-ce3f7c39-eceb-4221-a76/serviceAccounts/shipzen-eso-sa@project-ce3f7c39-eceb-4221-a76.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.cloudflare_origin_cert
  id = "projects/project-ce3f7c39-eceb-4221-a76/secrets/shipzen-cloudflare-origin-cert"
}

import {
  to = google_compute_subnetwork.subnet
  id = "projects/project-ce3f7c39-eceb-4221-a76/regions/us-central1/subnetworks/shipzen-subnet"
}

import {
  to = google_compute_router.router
  id = "projects/project-ce3f7c39-eceb-4221-a76/regions/us-central1/routers/shipzen-router"
}

import {
  to = google_compute_router_nat.nat
  id = "projects/project-ce3f7c39-eceb-4221-a76/regions/us-central1/routers/shipzen-router/shipzen-nat"
}

import {
  to = google_secret_manager_secret.redis_password
  id = "projects/project-ce3f7c39-eceb-4221-a76/secrets/shipzen-redis-password"
}
