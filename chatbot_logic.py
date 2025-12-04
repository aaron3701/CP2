import os
from llama_cpp import Llama
import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ---------- CONFIG ----------
BASE = os.path.dirname(os.path.abspath(__file__))
LLM_PATH = os.path.join(BASE, "models", "llm", "mistral-7b-instruct-v0.2.Q4_K_M.gguf")
RAG_DIR = os.path.join(BASE, "rag", "index")
DOCS_DIR = os.path.join(BASE, "rag", "docs")

# ---------- RAG ----------
def build_rag_if_missing():
    client = chromadb.PersistentClient(path=RAG_DIR)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-small-en-v1.5"
    )
    coll = client.get_or_create_collection("local_docs", embedding_function=ef)

    if coll.count() > 0:
        return coll

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    docs, ids = [], []
    i = 0
    for root, _, files in os.walk(DOCS_DIR):
        for fn in files:
            if fn.lower().endswith((".txt", ".md")):
                with open(os.path.join(root, fn), "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                for chunk in splitter.split_text(text):
                    docs.append(chunk)
                    ids.append(f"{fn}-{i}")
                    i += 1
    if docs:
        coll.add(documents=docs, ids=ids)
    return coll

def rag_query(coll, query, k=4):
    res = coll.query(query_texts=[query], n_results=k)
    docs = res.get("documents", [[]])[0]
    return "\n\n".join(docs)

# ---------- LLM ----------
def load_llm(
    gpu="auto",
    vram_gb=24,
    full_offload=True,
):
    n_gpu_layers = 999 if full_offload else 30
    n_batch = 2048 if vram_gb <= 8 else 1024
    n_threads = max(1, (os.cpu_count() or 8) - 1)
    
    return Llama(
        model_path=LLM_PATH,
        n_ctx=4096,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
        n_batch=n_batch,
        use_mmap=True,
        use_mlock=False,
        verbose=False,
    )

def chat(llm, user_text, context):
    system = """You are Julia, a helpful e-commerce assistant. 
    Use the CONTEXT provided to answer the user's question. 
    If the context contains 'Product Catalog', use it to find and recommend products.
    If the context contains 'Other Info', use it for general questions.
    Be friendly and concise."""
    
    prompt = f"<s>[INST] <<SYS>>{system}<</SYS>>\nCONTEXT:\n{context}\n\nUSER:\n{user_text}\n[/INST]"
    
    out = llm(prompt, max_tokens=512, temperature=0.6, stop=["</s>", "[INST]"])
    reply = out["choices"][0]["text"].strip()
    return reply