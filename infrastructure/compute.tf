# Cloud Run service for the Inference API (Real-time querying)
resource "google_cloud_run_v2_service" "api_service" {
  name     = "${var.project_id}-api"
  location = var.region

  template {
    containers {
      # Placeholder image, to be replaced with the actual pushed image from Artifact Registry
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
    }
  }
}

# Allow public access to the API (so the Frontend can call it)
resource "google_cloud_run_v2_service_iam_member" "api_public_access" {
  name     = google_cloud_run_v2_service.api_service.name
  location = google_cloud_run_v2_service.api_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Cloud Run service for the Background Worker (Asynchronous processing)
resource "google_cloud_run_v2_service" "worker_service" {
  name     = "${var.project_id}-worker"
  location = var.region

  template {
    containers {
      # Placeholder image, to be replaced with the actual pushed image
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
    }
  }
}

# The Worker shouldn't be publicly accessible, it should only be invoked by Pub/Sub
data "google_project" "project" {}

resource "google_cloud_run_v2_service_iam_member" "worker_pubsub_invoker" {
  name     = google_cloud_run_v2_service.worker_service.name
  location = google_cloud_run_v2_service.worker_service.location
  role     = "roles/run.invoker"
  # Best practice: create a specific service account for Pub/Sub push subscription
  # For now, we allow the default pubsub service account
  member   = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
