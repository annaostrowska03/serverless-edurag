# EduRAG
An asynchronous, highly scalable, AI-powered knowledge base utilizing the Retrieval-Augmented Generation (RAG) architecture.

EduRAG allows users to upload massive volumes of textual data (gigabytes of textbooks, manuals, or research papers) and interactively "chat" with them. To ensure scalability, the system decouples the responsive user interface from the heavy data processing layer. 

By leveraging a Serverless, event-driven architecture on Google Cloud Platform (GCP) and Firebase, uploaded documents are asynchronously parsed, chunked, and converted into embeddings in the background. Once processed, end-users can query the documents via a responsive UI, while the system dynamically retrieves the most relevant context to generate answers using Google's Vertex AI models.

## Architecture

The system is strictly divided into two decoupled workflows:

1.  **Asynchronous Ingestion Pipeline (Heavy Load):** Direct-to-GCS uploads trigger Pub/Sub queues. Cloud Run workers consume events, chunk PDFs, generate embeddings, and store them in a Vector Database.
2.  **Real-Time Inference Pipeline (Low Latency):** User queries from the Firebase UI are processed by a Cloud Function API. It retrieves the most relevant semantic context from the Vector DB and uses Vertex AI to stream back a generated response.

## Tech Stack

* **Cloud Provider:** Google Cloud Platform (GCP)
* **Infrastructure as Code:** Terraform
* **Frontend UI:** Firebase Hosting
* **Storage (Raw Files):** Google Cloud Storage (GCS)
* **Messaging:** Cloud Pub/Sub
* **Compute:** Cloud Run, Cloud Functions
* **Databases:** Firestore (Metadata), Vector DB (ChromaDB)
* **AI Models:** Vertex AI

## Repository Structure

* `/frontend`
* `/infrastructure` - Terraform scripts for provisioning GCP resources.
* `/workers` - Cloud Run services for asynchronous PDF chunking and vectorization.
* `/api` - Serverless functions for real-time chat inference.

## Team

* Anna Ostrowska 
* Michał Kukla
* Norbert Frydrysiak
