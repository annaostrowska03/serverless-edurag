import os
import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from google.cloud import storage
from langchain_google_vertexai import VertexAIEmbeddings, ChatVertexAI
from langchain.chains import LLMChain
from langchain_chroma import Chroma
import chromadb
from prompts import get_rag_prompt_template

app = Flask(__name__)
CORS(app) # Enable CORS for all routes, allowing the frontend to make requests

# Configuration loaded from environment variables
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-004")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-1.5-pro-preview-0409")
UPLOAD_BUCKET_NAME = os.environ.get("UPLOAD_BUCKET", "edurag-raw-pdfs")
CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb-service")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", 8000))
TOP_K = int(os.environ.get("TOP_K", 3))

# Initialize GCP Clients
storage_client = storage.Client()
embeddings_model = VertexAIEmbeddings(model_name=EMBEDDING_MODEL)
VERTEX_REGION = os.environ.get("GOOGLE_CLOUD_REGION", "europe-west3")
llm = ChatVertexAI(model_name=LLM_MODEL, temperature=0.2, location=VERTEX_REGION)

# Initialize ChromaDB remote client
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
vector_store = Chroma(
    client=chroma_client,
    collection_name="edurag_documents",
    embedding_function=embeddings_model
)

# Load the RAG prompt template from the separate file
prompt_template = get_rag_prompt_template()
llm_chain = LLMChain(llm=llm, prompt=prompt_template)

@app.route('/ask', methods=['POST'])
def ask_question():
    """
    Chat API (Cloud Functions / Cloud Run).
    Receives user questions and queries the vector database.
    """
    data = request.get_json()
    question = data.get("question") if data else None

    if not question:
        return jsonify({"error": "Question is required"}), 400

    try:
        # Similarity Search using Chroma DB
        docs = vector_store.similarity_search(question, k=TOP_K)
        
        if not docs:
            context = "No relevant context found."
        else:
            # Combine the chunks into a unified context string
            context = "\n\n---\n\n".join([doc.page_content for doc in docs])

        # 3. & 4. Build prompt with context and run LLM Generation using Gemini
        answer = llm_chain.run({"context": context, "question": question})

        return jsonify({"answer": answer, "retrieved_context": context})

    except Exception as e:
        print(f"Error processing question: {str(e)}")
        return jsonify({"error": "Failed to process the question.", "details": str(e)}), 500

@app.route('/generate-upload-url', methods=['GET'])
def generate_upload_url():
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"error": "Filename is required"}), 400

    try:
        import google.auth
        import google.auth.transport.requests as google_requests

        credentials, _ = google.auth.default()
        auth_request = google_requests.Request()
        credentials.refresh(auth_request)

        bucket = storage_client.bucket(UPLOAD_BUCKET_NAME)
        blob = bucket.blob(f"uploads/{filename}")

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="application/pdf",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
        return jsonify({"upload_url": url, "filename": f"uploads/{filename}"})
    except Exception as e:
        print(f"Error generating presigned URL: {str(e)}")
        return jsonify({"error": "Failed to generate URL", "details": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
