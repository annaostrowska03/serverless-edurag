import os
from flask import Flask, request

app = Flask(__name__)

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

    # TODO: LangChain Implementation
    # 1. Download file from GCS
    # 2. Split text into chunks
    # 3. Vectorize using Vertex AI
    # 4. Save to Vector DB

    return 'OK', 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
