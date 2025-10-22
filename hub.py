import os, tempfile, subprocess
import sounddevice as sd, soundfile as sf
from faster_whisper import WhisperModel
from llama_cpp import Llama
import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter
import msvcrt

# ---------- CONFIG ----------
BASE = os.path.dirname(os.path.abspath(__file__))
LLM_PATH = os.path.join(BASE, "models", "llm", "mistral-7b-instruct-v0.2.Q4_K_M.gguf")
RAG_DIR = os.path.join(BASE, "rag", "index")
DOCS_DIR = os.path.join(BASE, "rag", "docs")
PIPER_DIR = os.path.join(BASE, "models", "piper")    # contains piper.exe + voice .onnx & .json
PIPER_EXE = os.path.join(PIPER_DIR, "piper.exe")

WHISPER_SIZE = "base.en"  # base.en or small.en for speed/accuracy tradeoff
RECORD_SEC = 10  # seconds to record per input
SR = 16000

# ---------- STT ----------
def record_wav(seconds=RECORD_SEC, sr=SR):
    print("🎙️  Recording...")
    audio = sd.rec(int(seconds*sr), samplerate=sr, channels=1, dtype='float32')
    sd.wait()
    wav_path = tempfile.mkstemp(suffix=".wav")[1]
    sf.write(wav_path, audio, sr)
    print("✅ Saved:", wav_path)
    return wav_path

def stt_transcribe(wav_path):
    model = WhisperModel(WHISPER_SIZE, compute_type="int8")  # fast on CPU
    segments, _ = model.transcribe(wav_path)
    text = "".join([seg.text for seg in segments]).strip()
    return text

# ---------- RAG ----------
def build_rag_if_missing():
    client = chromadb.PersistentClient(path=RAG_DIR)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-small-en-v1.5")
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
def load_llm():
    return Llama(
        model_path=LLM_PATH,
        n_ctx=4096,
        n_threads=os.cpu_count(),   # use your cores
        n_gpu_layers=0              # CPU only
    )

def chat(llm, user_text, context):
    system = "You are Julia, a helpful local AI assistant. Use the CONTEXT when relevant."
    prompt = f"<s>[INST] <<SYS>>{system}<</SYS>>\nCONTEXT:\n{context}\n\nUSER:\n{user_text}\n[/INST]"
    out = llm(prompt, max_tokens=512, temperature=0.6, stop=["</s>", "[INST]"])
    reply = out["choices"][0]["text"].strip()
    # prepend Julia’s name
    return f"Julia: {reply}"

# ---------- TTS (Piper) ----------
def tts_piper(text, out_wav="reply.wav"):
    # Ensure piper.exe exists
    if not os.path.isfile(PIPER_EXE):
        raise FileNotFoundError(f"Piper not found at {PIPER_EXE}")

    # Pick first .onnx voice
    voices = [f for f in os.listdir(PIPER_DIR) if f.lower().endswith(".onnx")]
    if not voices:
        raise RuntimeError(f"No Piper voice .onnx found in {PIPER_DIR}")
    model_path = os.path.join(PIPER_DIR, voices[0])

    # Always use an absolute output path (inside PIPER_DIR or a temp dir)
    out_wav_path = os.path.join(PIPER_DIR, out_wav)  # or: tempfile.mkstemp(suffix=".wav")[1]

    # Run Piper without changing cwd; feed UTF-8 text
    cmd = [PIPER_EXE, "--model", model_path, "--output_file", out_wav_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    stdout, stderr = p.communicate(text)

    if p.returncode != 0 or not os.path.exists(out_wav_path):
        raise RuntimeError(f"Piper TTS failed (code {p.returncode}).\nSTDERR:\n{stderr}")

    # Now read the exact path we wrote
    data, sr = sf.read(out_wav_path, dtype='float32')
    sd.play(data, sr)
    sd.wait()

# ---------- MAIN ----------
def main():
    print("🔧 Building/Loading RAG…")
    coll = build_rag_if_missing()
    print("🧠 Loading LLM…")
    llm = load_llm()
    print("✅ Julia is ready. Press 't' to talk or 'q' to quit.")

    # Julia says hi right after loading
    greeting = "Hello, I am Julia. Press T whenever you want to talk to me."
    print(f"🤖 Julia: {greeting}")
    # tts_piper(greeting)

    while True:
        print("\nPress 't' to talk to Julia, or 'q' to quit...")
        key = msvcrt.getch().decode("utf-8").lower()

        if key == "q":
            farewell = "Goodbye, it was nice talking to you."
            print(f"🤖 Julia: {farewell}")
            # tts_piper(farewell)
            break
        if key != "t":
            continue  # ignore other keys

        #wav = record_wav()          # or record_wav_vad() if using VAD
        #text = stt_transcribe(wav)
        text = input("📝 You: ").strip()  # new text input
        if not text:
            print("…(no input detected)")
            continue
        print(f"👂 Heard: {text}")

        context = rag_query(coll, text)
        reply = chat(llm, text, context)
        print(f"🤖 {reply}")

        # tts_piper(reply)

if __name__ == "__main__":
    main()
