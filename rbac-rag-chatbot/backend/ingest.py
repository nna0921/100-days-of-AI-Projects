import os
import pandas as pd
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

load_dotenv()


DOCUMENT_MAP = [
    ("data/engineering/engineering_master_doc.md", "engineering"),
    ("data/finance/financial_summary.md",          "finance"),
    ("data/finance/quarterly_financial_report.md", "finance"),
    ("data/general/employee_handbook.md",          "general"),
    ("data/marketing/market_report_q4_2024.md",    "marketing"),
    ("data/marketing/marketing_report_2024.md",    "marketing"),
    ("data/marketing/marketing_report_q1_2024.md", "marketing"),
    ("data/marketing/marketing_report_q2_2024.md", "marketing"),
    ("data/marketing/marketing_report_q3_2024.md", "marketing"),
]

HR_CSV = "data/hr/hr_data.csv"

def load_markdown(filepath: str, department: str) -> list[Document]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    return [Document(
        page_content=content,
        metadata={"department": department, "source": os.path.basename(filepath)}
    )]

def load_csv(filepath: str, department: str) -> list[Document]:
    df = pd.read_csv(filepath)
    docs = []
    chunk_size = 10
    for i in range(0, len(df), chunk_size):
        chunk = df.iloc[i:i+chunk_size].to_string(index=False)
        docs.append(Document(
            page_content=chunk,
            metadata={"department": department, "source": os.path.basename(filepath)}
        ))
    return docs

def ingest():
    all_docs = []

    for filepath, department in DOCUMENT_MAP:
        full_path = os.path.join(os.path.dirname(__file__), "..", filepath)
        print(f"Loading {full_path}...")
        all_docs.extend(load_markdown(full_path, department))

    full_csv_path = os.path.join(os.path.dirname(__file__), "..", HR_CSV)
    print(f"Loading {full_csv_path}...")
    all_docs.extend(load_csv(full_csv_path, "hr"))

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_documents(all_docs)
    print(f"Total chunks: {len(chunks)}")

    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    
    import time
    batch_size = 50
    
    vectorstore = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        print(f"Ingesting batch {i//batch_size + 1}...")
        vectorstore.add_documents(batch)
        if i + batch_size < len(chunks):
            print("Sleeping for 60 seconds to avoid rate limit...")
            time.sleep(60)

    print(f"Ingestion complete. {len(chunks)} chunks stored in ChromaDB.")

if __name__ == "__main__":
    ingest()