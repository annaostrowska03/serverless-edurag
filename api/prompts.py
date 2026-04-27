from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

SYSTEM_PROMPT = """You are an AI assistant for the EduRAG knowledge base.
Use the following context to answer the user's question. If you don't know the answer or the context doesn't contain it, say "I don't know based on the provided context".

Context:
{context}"""

USER_PROMPT = """Question:
{question}"""

def get_rag_prompt_template() -> ChatPromptTemplate:
    """Returns the LangChain ChatPromptTemplate for the RAG workflow."""
    system_message_prompt = SystemMessagePromptTemplate.from_template(SYSTEM_PROMPT)
    human_message_prompt = HumanMessagePromptTemplate.from_template(USER_PROMPT)
    
    return ChatPromptTemplate.from_messages([
        system_message_prompt,
        human_message_prompt
    ])
