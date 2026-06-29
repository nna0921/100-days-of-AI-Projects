from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv

load_dotenv()

PROMPT_TEMPLATE = """You are FinSolve's internal AI assistant. Answer the employee's question using ONLY the context provided below. 
If the context doesn't contain enough information, say: "I don't have sufficient information to answer that based on your access level."
Always cite the source document(s) at the end of your response.

Context:
{context}

Question: {question}

Answer:"""

embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
vectorstore = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

def get_rag_response(query: str, allowed_departments: list[str]) -> dict:
    retriever = vectorstore.as_retriever(
        search_kwargs={
            "k": 5,
            "filter": {"department": {"$in": allowed_departments}}
        }
    )

    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=["context", "question"]
    )

    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.2
    )

    chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt}
    )

    result = chain.invoke({"query": query})

    sources = list(set(
        doc.metadata["source"] for doc in result["source_documents"]
    ))

    return {
        "answer": result["result"],
        "sources": sources
    }