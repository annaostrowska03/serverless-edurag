# GCS Bucket for storing raw PDF files
resource "google_storage_bucket" "pdf_upload_bucket" {
  name                        = "${var.project_id}-raw-pdfs"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true

  # for now simple rule (delete after 30 days), can be changed later
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}
