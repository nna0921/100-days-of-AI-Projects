from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

load_dotenv()

PROMPT_TEMPLATE = """You are FinSolve's internal AI assistant. Answer the employee's question using ONLY the context provided below. 
If the context doesn't contain enough information, say: "I don't have sufficient information to answer that based on your access level."
Always cite the source document(s) at the end of your response.

Context:
{context}

Question: {question}

Answer:"""

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
vectorstore = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

def deduplicate_docs(docs, limit: int = 8):
    """Keep the best-ranked copy of each chunk and preserve source diversity."""
    unique_docs = []
    seen_content = set()

    for doc in docs:
        content_key = doc.page_content.strip()
        if content_key in seen_content:
            continue
        seen_content.add(content_key)
        unique_docs.append(doc)
        if len(unique_docs) == limit:
            break

    return unique_docs


def format_docs(docs):
    return "\n\n---\n\n".join(
        f"[Source: {doc.metadata.get('source', 'Unknown document')}]\n{doc.page_content}"
        for doc in docs
    )

def get_rag_response(query: str, allowed_departments: list[str]) -> dict:
    retriever = vectorstore.as_retriever(
        search_kwargs={
            "k": 24,
            "filter": {"department": {"$in": allowed_departments}}
        }
    )

    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=["context", "question"]
    )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.2,
        max_retries=0,
        timeout=10.0
    )

    source_docs = deduplicate_docs(retriever.invoke(query))

    chain = (
        {"context": lambda _: format_docs(source_docs), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    answer = chain.invoke(query)

    sources = list(dict.fromkeys(
        doc.metadata["source"] for doc in source_docs
    ))

    return {
        "answer": answer,
        "sources": sources
    }
