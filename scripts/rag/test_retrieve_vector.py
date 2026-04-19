from pathlib import Path
import chromadb
from openai import OpenAI

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
CHROMA_DIR = ROOT / "data" / "chroma_db"
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"

def load_api_key(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("sk-"):
        return text
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value.startswith("sk-"):
                return value
        if line.startswith("sk-"):
            return line
    raise ValueError("No valid OpenAI key found.")

client = OpenAI(api_key=load_api_key(KEY_FILE))
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = chroma_client.get_collection("anime_chunks")

def get_embedding(text: str):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding

query = "我想看压抑一点、带政治冲突和战争感的动画"
query_embedding = get_embedding(query)

results = collection.query(
    query_embeddings=[query_embedding],
    n_results=8
)

for i, doc in enumerate(results["documents"][0], 1):
    meta = results["metadatas"][0][i - 1]
    print(f"\n=== Result {i} ===")
    print("title:", meta["title"])
    print("section:", meta["section"])
    print(doc)
