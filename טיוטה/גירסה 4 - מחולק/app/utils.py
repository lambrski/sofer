# app/utils.py
import os
import re
import shutil
import docx
import PyPDF2
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GOOGLE_API_KEY)
VECTORSTORE_ROOT = "vectorstores"

def _clean_ai_division_output(raw_text: str) -> str:
    match = re.search(r"פרק\s+\d+", raw_text)
    if match:
        return raw_text[match.start():]
    return raw_text.strip()

def _safe_join_under(base: str, path_rel: str) -> str:
    base_abs = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base_abs, path_rel.lstrip("/\\")))
    if os.path.commonpath([full, base_abs]) != base_abs:
        raise ValueError("Path traversal attempt detected.")
    return full

def _guess_ext(filename: str) -> str:
    return (os.path.splitext(filename)[1] or "").lower()

def extract_text_from_file(file_path: str) -> str:
    ext = _guess_ext(file_path)
    text = ""
    try:
        if ext == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
        elif ext == '.docx':
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        return f"Error reading file: {os.path.basename(file_path)}"
    return text

def create_vector_index(text: str, index_path: str):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = text_splitter.split_text(text)
    db = FAISS.from_texts(docs, embeddings)
    db.save_local(index_path)

def get_relevant_context_from_index(query: str, index_path: str, k=4) -> str:
    if not os.path.exists(index_path):
        return ""
    db = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
    results = db.similarity_search(query, k=k)
    return "\n---\n".join([doc.page_content for doc in results])
