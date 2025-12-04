import os
import time
from datetime import datetime
 
# ------------- LLM / RAG deps -------------
from llama_cpp import Llama
import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter
 
# ------------- Firebase / Firestore -------------
import firebase_admin
from firebase_admin import credentials, firestore
 
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
""" def load_llm():
    return Llama(
        model_path=LLM_PATH,
        n_ctx=4096,
        n_threads=os.cpu_count(),
        n_gpu_layers=0,   # CPU only
        verbose=False,    # quieter logs
    ) """ 
 
def load_llm(
    gpu="auto",           # "cuda", "metal", "rocm", or "auto"
    vram_gb=24,            # set your GPU VRAM in GB (rough guide)
    full_offload=True,    # try to offload all layers when possible
):
    """
    Load llama.cpp with GPU acceleration.
    - Set n_gpu_layers to a large number (capped internally) to offload as many layers as possible.
    - Tune n_batch for throughput; increase if you have VRAM headroom.
    """
 
    # Heuristic: model is 7B Q4_K_M → ~3.8–4.2 GB when fully offloaded
    # If you have ≥8 GB VRAM, full offload is usually fine.
    n_gpu_layers = 999 if full_offload else 30
 
    # Bigger batches = faster, but needs VRAM. 512 is safe for 7B; try 1024–2048 if you have room.
    n_batch = 2048 if vram_gb <= 8 else 1024
 
    # Threads for CPU-side ops (sampling, tokenization)
    n_threads = max(1, (os.cpu_count() or 8) - 1)
 
    # Optional: multi-GPU split (CUDA only). Example: 2 GPUs 50/50
    # tensor_split = [0.5, 0.5]
    tensor_split = None
 
    return Llama(
        model_path=LLM_PATH,
        n_ctx=4096,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,   # <— enables GPU offload
        n_batch=n_batch,
        # tensor_split=tensor_split,  # uncomment if using multi-GPU
        use_mmap=True,
        use_mlock=False,             # set True if you want to lock pages in RAM
        verbose=False,
    )
 
 
def chat(llm, user_text, context):
    system = "You are Julia, a helpful local AI assistant. Use the CONTEXT when relevant."
    prompt = f"<s>[INST] <<SYS>>{system}<</SYS>>\nCONTEXT:\n{context}\n\nUSER:\n{user_text}\n[/INST]"
    out = llm(prompt, max_tokens=512, temperature=0.6, stop=["</s>", "[INST]"])
    reply = out["choices"][0]["text"].strip()
    return reply   # return plain model text (no "Julia: " prefix)
 
# ---------- Firestore ----------
def init_firestore():
    """
    Initialize Firebase Admin SDK. Uses GOOGLE_APPLICATION_CREDENTIALS if set,
    else tries ./serviceAccountKey.json.
    """
    if not firebase_admin._apps:
        default_json = os.path.join(BASE, "serviceAccountKey.json")
        if os.path.isfile(default_json):
            cred = credentials.Certificate(default_json)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()  # ADC
    return firestore.client()
 
# ---------- MAIN ----------
def main():
    print("🔧 Building/Loading RAG…")
    coll = build_rag_if_missing()
 
    print("🧠 Loading LLM…")
    llm = load_llm()
 
    print("☁️  Connecting to Firestore…")
    db = init_firestore()
    messages_ref = db.collection("messages")  # change to input("")
    reply_ref = db.collection("reply")  # <-- new target collection //remove
 
    # Listen only to pending messages
    query_ref = messages_ref.where("status", "==", "pending")
 
    print("✅ Watching 'messages' (status == 'pending') and writing replies to 'reply'…\n")
 
    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name not in ("ADDED", "MODIFIED"):
                continue
 
            doc = change.document
            data = doc.to_dict() or {}
            status = (data.get("status") or "").lower()
            text = (data.get("text") or "").strip()
            if status != "pending" or not text:
                continue
 
            conv_id = data.get("conv_id", "")
            role = data.get("role", "")
            created_at = data.get("created_at", "")
            print("----- NEW MESSAGE --------------------------------")
            print(f"conv_id: {conv_id}")
            print(f"role:    {role}")
            print(f"time:    {created_at}")
            print(f"status:  {status}")
            print(f"TEXT ->  {text}")
            print("--------------------------------------------------")
 
            # Build context & query LLM
            try:
                context = rag_query(coll, text)
                reply = chat(llm, text, context)
            except Exception as e:
                print(f"❌ LLM error: {e}")
                try:
                    doc.reference.update(
                        {
                            "status": "error",
                            "error_message": str(e),
                            "processed_at": firestore.SERVER_TIMESTAMP,
                        }
                    )
                except Exception as ue:
                    print(f"❌ Failed to update error status: {ue}")
                continue
 
            print("REPLY -----------------------------------------")
            print(reply)
            print("--------------------------------------------------\n")
 
            # Mark original message as processed
            try:
                doc.reference.update(
                    {
                        "reply": reply,
                        "status": "replied",
                        "role": "assistant",
                        "processed_at": firestore.SERVER_TIMESTAMP,
                    }
                )
            except Exception as ue:
                print(f"Could not update message with reply: {ue}")
 
            # ---- Write reply into its own collection 'reply' ----
            try:
                reply_ref.add(
                    {
                        "created_at": firestore.SERVER_TIMESTAMP,
                        "text": reply,
                        # If you later want to link it back:
                        # "conv_id": conv_id,
                        # "source_message_id": doc.id,
                    }
                )
            except Exception as we:
                print(f"⚠️ Could not write to 'reply': {we}")
 
    # Start realtime listener
    stop = query_ref.on_snapshot(on_snapshot)
 
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹️  Stopping listener…")
        stop()
 


if __name__ == "__main__":
    main()