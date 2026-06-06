# Cloud Run service for Inference API (Real-time querying)
resource "google_cloud_run_v2_service" "api_service" {
  name     = "${var.project_id}-api"
  location = var.region

  template {
    service_account = google_service_account.cloud_run_sa.email

    containers {
      image = "europe-west3-docker.pkg.dev/${var.project_id}/edurag-repo/api:latest"

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "CHROMA_HOST"
        value = var.chroma_host
      }
      env {
        name  = "CHROMA_PORT"
        value = "8000"
      }
      env {
        name  = "UPLOAD_BUCKET"
        value = "${var.project_id}-raw-pdfs"
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = "text-embedding-004"
      }
      env {
      name  = "LLM_MODEL"
      value = "gemini-2.5-flash"
    }
	env {
  name  = "GOOGLE_CLOUD_REGION"
  value = "europe-west3"
}
    }
  }

  depends_on = [google_project_service.required_apis]
}

# Public access to API (frontend must reach it)
resource "google_cloud_run_v2_service_iam_member" "api_public_access" {
  name     = google_cloud_run_v2_service.api_service.name
  location = google_cloud_run_v2_service.api_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Cloud Run service for Background Worker (Asynchronous processing)
resource "google_cloud_run_v2_service" "worker_service" {
  name     = "${var.project_id}-worker"
  location = var.region

  template {
    service_account = google_service_account.cloud_run_sa.email

    containers {
      image = "europe-west3-docker.pkg.dev/${var.project_id}/edurag-repo/worker:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "CHROMA_HOST"
        value = var.chroma_host
      }
      env {
        name  = "CHROMA_PORT"
        value = "8000"
      }
      env {
        name  = "FIRESTORE_COLLECTION"
        value = "documents"
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = "text-embedding-004"
      }
    }
  }

  depends_on = [google_project_service.required_apis]
}

data "google_project" "project" {}

resource "google_cloud_run_v2_service_iam_member" "worker_pubsub_invoker" {
  name     = google_cloud_run_v2_service.worker_service.name
  location = google_cloud_run_v2_service.worker_service.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# Service Account for Cloud Run (instead of default)
resource "google_service_account" "cloud_run_sa" {
  account_id   = "edurag-cloud-run-sa"
  display_name = "EduRAG Cloud Run Service Account"
}

resource "google_project_iam_member" "cloud_run_sa_roles" {
  for_each = toset([
    "roles/storage.objectAdmin",
    "roles/datastore.user",
    "roles/aiplatform.user",
    "roles/pubsub.subscriber",
    "roles/iam.serviceAccountTokenCreator",
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}
# Artifact Registry - Docker image repository
resource "google_artifact_registry_repository" "edurag_repo" {
  location      = var.region
  repository_id = "edurag-repo"
  format        = "DOCKER"

  depends_on = [google_project_service.required_apis]
}
