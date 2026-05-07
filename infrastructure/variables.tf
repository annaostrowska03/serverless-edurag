variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "europe-west3"
}

variable "chroma_host" {
  description = "External IP address of the ChromaDB Compute Engine instance"
  type        = string
  default     = "localhost"
}
