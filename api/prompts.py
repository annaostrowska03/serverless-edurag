from langchain.prompts import PromptTemplate

RAG_PROMPT_TEMPLATE = """You are an AI assistant for the EduRAG knowledge base.
Use the following context to answer the question. If you don't know the answer or the context doesn't contain it, say "I don't know based on the provided context".

Context:
{context}

Question:
{question}

Answer:"""

def get_rag_prompt_template() -> PromptTemplate:
    """Returns the LangChain PromptTemplate for the RAG workflow."""
    return PromptTemplate(
        input_variables=["context", "question"],
        template=RAG_PROMPT_TEMPLATE
    )
