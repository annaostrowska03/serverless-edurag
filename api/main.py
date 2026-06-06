import datetime
import json
import os
import re

import chromadb
import firebase_admin
from firebase_admin import auth as firebase_auth
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from google.cloud import firestore, storage
from langchain_chroma import Chroma
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_vertexai import ChatVertexAI, VertexAIEmbeddings

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "DELETE", "OPTIONS"],
)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-004")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-1.5-pro-preview-0409")
UPLOAD_BUCKET_NAME = os.environ.get("UPLOAD_BUCKET", "edurag-raw-pdfs")
CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb-service")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", 8000))
TOP_K = int(os.environ.get("TOP_K", 3))
VERTEX_REGION = os.environ.get("GOOGLE_CLOUD_REGION", "europe-west3")

storage_client = storage.Client()
db = firestore.Client()
embeddings_model = VertexAIEmbeddings(model_name=EMBEDDING_MODEL)
llm = ChatVertexAI(model_name=LLM_MODEL, temperature=0.2, location=VERTEX_REGION)

chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
vector_store = Chroma(
    client=chroma_client,
    collection_name="edurag_documents",
    embedding_function=embeddings_model,
)

firebase_admin.initialize_app(
    options={"projectId": os.environ.get("GOOGLE_CLOUD_PROJECT", "edurag-495620")}
)


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return ("", 204)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    response.headers["Access-Control-Allow-Origin"] = origin or "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Vary"] = "Origin"
    return response


def get_request_data():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict(flat=True)


def get_request_value(name, default=None):
    data = get_request_data()
    if name in data:
        return data.get(name)
    return request.args.get(name, default)


def parse_json_field(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def get_id_token():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    for key in ("id_token", "token"):
        value = get_request_value(key)
        if value:
            return value

    return None


def verify_token():
    token = get_id_token()
    if not token:
        return None
    try:
        decoded = firebase_auth.verify_id_token(token)
        return decoded["uid"]
    except Exception as exc:
        print(f"verify_token FAILED: {type(exc).__name__}: {exc}")
        return None


def sanitize(value):
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", value).strip("_") or "General"


def build_doc_ref(user_id, doc_id):
    return db.collection("users").document(user_id).collection("documents").document(doc_id)


@app.route("/ask", methods=["POST", "OPTIONS"])
def ask_question():
    user_id = verify_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = get_request_data()
    question = data.get("question")
    doc_ids = parse_json_field(data.get("doc_ids"), [])
    history = parse_json_field(data.get("history"), [])

    if not question:
        return jsonify({"error": "Question is required"}), 400

    try:
        chroma_filter = {"doc_id": {"$in": doc_ids}} if doc_ids else {"user_id": user_id}
        docs = vector_store.similarity_search(question, k=TOP_K, filter=chroma_filter)

        if not docs:
            context = "No relevant context found in the selected documents."
            sources = []
        else:
            context = "\n\n---\n\n".join(doc.page_content for doc in docs)
            seen = set()
            sources = []
            for doc in docs:
                filename = doc.metadata.get("filename") or os.path.basename(doc.metadata.get("source", "Unknown"))
                page = doc.metadata.get("page", 0) + 1
                subject = doc.metadata.get("subject", "")
                key = f"{filename}:{page}"
                if key in seen:
                    continue
                seen.add(key)
                sources.append(
                    {
                        "filename": filename,
                        "page": page,
                        "subject": subject,
                        "excerpt": doc.page_content[:250].strip(),
                    }
                )

        from prompts import SYSTEM_PROMPT

        messages = [SystemMessage(content=SYSTEM_PROMPT.format(context=context))]
        for msg in history[-6:]:
            if msg.get("role") == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg.get("role") == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=question))

        def generate():
            try:
                for chunk in llm.stream(messages):
                    if chunk.content:
                        yield f"data: {json.dumps({'token': chunk.content})}\n\n"
                yield f"data: {json.dumps({'sources': sources, 'done': True})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as exc:
        print(f"Error processing question: {exc}")
        return jsonify({"error": "Failed to process the question.", "details": str(exc)}), 500


@app.route("/generate-upload-url", methods=["GET", "POST", "OPTIONS"])
def generate_upload_url():
    user_id = verify_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    filename = get_request_value("filename")
    subject = sanitize(get_request_value("subject", "General"))

    if not filename:
        return jsonify({"error": "Filename is required"}), 400

    try:
        import google.auth
        import google.auth.transport.requests as google_requests

        credentials, _ = google.auth.default()
        google_requests.Request()(credentials)

        gcs_path = f"uploads/{user_id}/{subject}/{filename}"
        doc_id = gcs_path.replace("/", "_")

        bucket = storage_client.bucket(UPLOAD_BUCKET_NAME)
        blob = bucket.blob(gcs_path)

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="application/pdf",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )

        build_doc_ref(user_id, doc_id).set(
            {
                "status": "Uploading",
                "filename": filename,
                "subject": subject,
                "user_id": user_id,
                "storage_path": gcs_path,
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )

        return jsonify(
            {
                "upload_url": url,
                "document_id": doc_id,
                "user_id": user_id,
            }
        )
    except Exception as exc:
        print(f"Error generating presigned URL: {exc}")
        return jsonify({"error": "Failed to generate URL", "details": str(exc)}), 500


@app.route("/documents/<doc_id>", methods=["DELETE", "POST", "OPTIONS"])
def delete_document(doc_id):
    user_id = verify_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        doc_ref = build_doc_ref(user_id, doc_id)
        doc_snap = doc_ref.get()
        if not doc_snap.exists:
            return jsonify({"error": "Document not found"}), 404

        data = doc_snap.to_dict()
        gcs_path = data.get("storage_path") or f"uploads/{user_id}/{data.get('subject', 'General')}/{data.get('filename', '')}"

        try:
            collection = chroma_client.get_collection("edurag_documents")
            results = collection.get(where={"doc_id": doc_id})
            if results["ids"]:
                collection.delete(ids=results["ids"])
        except Exception as exc:
            print(f"ChromaDB delete warning: {exc}")

        try:
            bucket = storage_client.bucket(UPLOAD_BUCKET_NAME)
            blob = bucket.blob(gcs_path)
            if blob.exists():
                blob.delete()
        except Exception as exc:
            print(f"GCS delete warning: {exc}")

        doc_ref.delete()
        return jsonify({"deleted": doc_id})
    except Exception as exc:
        print(f"Error deleting document {doc_id}: {exc}")
        return jsonify({"error": "Failed to delete document", "details": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
