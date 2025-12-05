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

def build_product_index_if_missing(products, path=RAG_DIR, collection_name="products", force_rebuild=False):
    """
    Build a persistent Chroma collection for product semantic search.
    products: list of dicts with keys: id, name, description, category, price, image, (optional) gender, etc.
    force_rebuild: if True, delete and rebuild the collection (useful when products change)
    """
    client = chromadb.PersistentClient(path=path)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-small-en-v1.5"
    )
    
    # If force_rebuild is True, delete the old collection
    if force_rebuild:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass  # Collection doesn't exist, that's fine
    
    coll = client.get_or_create_collection(collection_name, embedding_function=ef)

    # If already populated AND not forcing rebuild, skip
    if coll.count() > 0 and not force_rebuild:
        return coll

    ids, docs, metadatas = [], [], []
    for p in products:
        pid = str(p.get("id") or p.get("product_id") or p.get("doc_id") or p.get("id_str") or "")
        if not pid:
            continue
        text = " | ".join([
            str(p.get("name", "")).strip(),
            str(p.get("category", "")).strip(),
            str(p.get("description", "")).strip()
        ])
        ids.append(pid)
        docs.append(text)
        metadatas.append({
            "name": p.get("name"),
            "category": p.get("category"),
            "price": p.get("price"),
            "image": p.get("image"),
            **({k: p[k] for k in ("gender","color","in_stock") if k in p})
        })

    if docs:
        coll.add(documents=docs, metadatas=metadatas, ids=ids)
    return coll

def product_index_query(coll, query, n_results=8, where=None):
    """
    Query the product collection.
    where: optional metadata filter dict, e.g. {"gender": "male"}
    Returns list of dicts: {id, meta, distance}
    """
    if coll is None:
        return []

    try:
        res = coll.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["metadatas", "distances", "documents"]
        )
    except TypeError:
        # Fallback for older chroma versions
        res = coll.query(
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "distances", "documents"]
        )

    ids = res.get("ids", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0] if "distances" in res else [None]*len(ids)

    out = []
    for i, pid in enumerate(ids):
        out.append({"id": pid, "meta": metas[i], "distance": dists[i]})
    return out

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