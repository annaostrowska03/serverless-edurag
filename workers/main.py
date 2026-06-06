import os
import json
import base64
from flask import Flask, request
from google.cloud import storage, firestore
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_vertexai import VertexAIEmbeddings
from langchain_chroma import Chroma
import chromadb

app = Flask(__name__)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-004")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 100))
CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb-service")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", 8000))

storage_client = storage.Client()
db = firestore.Client()
embeddings_model = VertexAIEmbeddings(model_name=EMBEDDING_MODEL)

chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
vector_store = Chroma(
    client=chroma_client,
    collection_name="edurag_documents",
    embedding_function=embeddings_model
)


def get_doc_ref(user_id, doc_id):
    """Returns the Firestore document reference based on whether it's user-scoped or legacy."""
    if user_id and user_id != "legacy":
        return db.collection("users").document(user_id).collection("documents").document(doc_id)
    return db.collection("documents").document(doc_id)


@app.route("/", methods=["POST"])
def process_document():
    envelope = request.get_json()
    if not envelope:
        return "Bad Request: no Pub/Sub message received", 400

    pubsub_message = envelope.get("message", {})
    if not pubsub_message or "data" not in pubsub_message:
        return "Bad Request: missing data in message", 400

    try:
        data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        event_payload = json.loads(data)
    except Exception as e:
        return f"Error decoding message: {e}", 400

    bucket_name = event_payload.get("bucket")
    file_name = event_payload.get("name")

    if not bucket_name or not file_name:
        return "OK", 200

    print(f"Processing: gs://{bucket_name}/{file_name}")

    doc_id = file_name.replace("/", "_")

    # Parse path: uploads/{user_id}/{subject}/{filename}
    # Falls back gracefully for legacy paths: uploads/{filename}
    parts = file_name.split("/")
    if len(parts) >= 4 and parts[0] == "uploads":
        user_id = parts[1]
        subject = parts[2]
        original_filename = "/".join(parts[3:])
    elif len(parts) >= 2 and parts[0] == "uploads":
        user_id = "legacy"
        subject = "General"
        original_filename = os.path.basename(file_name)
    else:
        user_id = "legacy"
        subject = "General"
        original_filename = os.path.basename(file_name)

    doc_ref = get_doc_ref(user_id, doc_id)
    doc_ref.set({
        "status": "Downloading",
        "filename": original_filename,
        "subject": subject,
        "user_id": user_id,
    }, merge=True)

    tmp_file_path = f"/tmp/{doc_id}"

    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        blob.download_to_filename(tmp_file_path)
        print(f"Downloaded to {tmp_file_path}")

        doc_ref.update({"status": "Chunking"})

        loader = PyPDFLoader(tmp_file_path)
        documents = loader.load()

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP
        )
        chunks = text_splitter.split_documents(documents)
        print(f"Split into {len(chunks)} chunks")

        # Attach user/subject/doc metadata to every chunk so the API can filter
        for chunk in chunks:
            chunk.metadata["doc_id"] = doc_id
            chunk.metadata["user_id"] = user_id
            chunk.metadata["subject"] = subject
            chunk.metadata["filename"] = original_filename

        doc_ref.update({"status": "Vectorizing", "total_chunks": len(chunks)})

        vector_store.add_documents(chunks)
        print(f"Stored {len(chunks)} chunks in ChromaDB")

        doc_ref.update({"status": "Ready"})

    except Exception as e:
        print(f"Error processing {file_name}: {e}")
        doc_ref.update({"status": "Failed", "error": str(e)})
        return f"Error: {e}", 500
    finally:
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
