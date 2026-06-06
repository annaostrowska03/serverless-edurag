# Pub/Sub topic for notifications about new files from GCS
resource "google_pubsub_topic" "pdf_uploads_topic" {
  name = "pdf-uploads-topic"
}

# Subscription from which our Worker will read
resource "google_pubsub_subscription" "pdf_uploads_sub" {
  name  = "pdf-uploads-subscription"
  topic = google_pubsub_topic.pdf_uploads_topic.name

  push_config {
      push_endpoint = google_cloud_run_v2_service.worker_service.uri

      oidc_token {
        service_account_email = google_service_account.cloud_run_sa.email
      }
  }


  ack_deadline_seconds = 600
}

# Permission for Cloud Storage to send messages to Pub/Sub
data "google_storage_project_service_account" "gcs_account" {}

resource "google_pubsub_topic_iam_binding" "binding" {
  topic   = google_pubsub_topic.pdf_uploads_topic.id
  role    = "roles/pubsub.publisher"
  members = ["serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"]
}

# Notification GCS -> Pub/Sub
resource "google_storage_notification" "pdf_upload_notification" {
  bucket         = google_storage_bucket.pdf_upload_bucket.name
  payload_format = "JSON_API_V1"
  topic          = google_pubsub_topic.pdf_uploads_topic.id
  event_types    = ["OBJECT_FINALIZE"] # Triggered only upon successful file upload
  
  depends_on = [google_pubsub_topic_iam_binding.binding]
}
