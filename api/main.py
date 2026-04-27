import os
from flask import Flask, jsonify, request

app = Flask(__name__)

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

    # TODO: RAG Implementation
    # 1. Convert question to vector
    # 2. Query Vector DB for the most similar chunks
    # 3. Build prompt with context for Vertex AI (Gemini)
    # 4. Return the generated answer

    return jsonify({"answer": f"Received question: '{question}'. RAG module under construction."})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
