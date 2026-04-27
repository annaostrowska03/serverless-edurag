import os
import json
import base64
from flask import Flask, request
from google.cloud import storage
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

app = Flask(__name__)
# Initialize the GCS client (it automatically picks up credentials in Cloud Run)
storage_client = storage.Client()

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

    # Download file from GCS
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    
    tmp_file_path = f"/tmp/{os.path.basename(file_name)}"
    blob.download_to_filename(tmp_file_path)
    print(f"Successfully downloaded {file_name} to local temp storage.")

    # Extract text and split into chunks using LangChain
    loader = PyPDFLoader(tmp_file_path)
    documents = loader.load()
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=100
    )
    chunks = text_splitter.split_documents(documents)
    print(f"Split {file_name} into {len(chunks)} chunks.")

    # Vectorize using Vertex AI
    # TODO: Initialize VertexAIEmbeddings(model_name="textembedding-gecko@latest")
    # embeddings = [chunk.page_content for chunk in chunks] -> get vectors

    # Save to Vector DB
    # TODO: Push chunks and vectors to ChromaDB or Vertex AI Vector Search

    # Cleanup local file
    if os.path.exists(tmp_file_path):
        os.remove(tmp_file_path)

    return 'OK', 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
