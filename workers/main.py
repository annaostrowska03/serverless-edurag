import os
import json
import base64
from flask import Flask, request
from google.cloud import storage, firestore
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_vertexai import VertexAIEmbeddings

app = Flask(__name__)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-004")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 100))
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "documents")

# Initialize the GCS and Firestore clients (they automatically pick up credentials in Cloud Run)
storage_client = storage.Client()
db = firestore.Client()
embeddings_model = VertexAIEmbeddings(model_name=EMBEDDING_MODEL)

@app.route('/', methods=['POST'])
def process_document():
    """
    Entry point for Cloud Run.
    Invoked by Pub/Sub messages to process PDFs,
    split text into chunks, and generate embeddings.
    """
    envelope = request.get_json()
    if not envelope:
        return 'Bad Request: no Pub/Sub message received', 400

    pubsub_message = envelope.get('message', {})
    if not pubsub_message or 'data' not in pubsub_message:
        return 'Bad Request: missing data in message', 400

    # Parse the Pub/Sub message payload triggered by GCS
    try:
        data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        event_payload = json.loads(data)
    except Exception as e:
        return f'Error decoding message: {str(e)}', 400

    bucket_name = event_payload.get('bucket')
    file_name = event_payload.get('name')

    if not bucket_name or not file_name:
        print("Not a valid GCS event payload.")
        return 'OK', 200

    print(f"Processing file: {file_name} from bucket: {bucket_name}")

    doc_id = file_name.replace("/", "_")
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(doc_id)
    doc_ref.set({"status": "Downloading", "filename": file_name})

    try:
        # Download file from GCS
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        
        tmp_file_path = f"/tmp/{os.path.basename(file_name)}"
        blob.download_to_filename(tmp_file_path)
        print(f"Successfully downloaded {file_name} to local temp storage.")
        
        doc_ref.update({"status": "Chunking"})

        # Extract text and split into chunks using LangChain
        loader = PyPDFLoader(tmp_file_path)
        documents = loader.load()
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, 
            chunk_overlap=CHUNK_OVERLAP
        )
        chunks = text_splitter.split_documents(documents)
        print(f"Split {file_name} into {len(chunks)} chunks.")
        
        doc_ref.update({"status": "Vectorizing", "total_chunks": len(chunks)})

        # Vectorize using Vertex AI
        # Generate embeddings for the chunks using the initialized model
        texts = [chunk.page_content for chunk in chunks]
        embeddings = embeddings_model.embed_documents(texts)
        print(f"Generated {len(embeddings)} embeddings using Vertex AI.")

        # Save to Vector DB
        # TODO: Push vectors (embeddings) and metadata (chunks) to vector db
        
        doc_ref.update({"status": "Ready"})

    except Exception as e:
        print(f"Error processing document {file_name}: {str(e)}")
        doc_ref.update({"status": "Failed", "error": str(e)})
        return f"Error: {str(e)}", 500
    finally:
        # Cleanup local file
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

    return 'OK', 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
