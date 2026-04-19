import json
from pathlib import Path

import chromadb
from openai import OpenAI

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
CHROMA_DIR = ROOT / "data" / "chroma_db"
IN_FILE = DATA_DIR / "anime_chunks.jsonl"
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"


def load_api_key(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Key file not found: {path}")

    text = path.read_text(encoding="utf-8").strip()

    # 情况1：整个文件就是 sk-...
    if text.startswith("sk-"):
        return text

    # 情况2：文件里有 OPENAI_API_KEY=sk-...
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("OPENAI_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value.startswith("sk-"):
                return value

        if line.startswith("sk-"):
            return line

    raise ValueError(
        "No valid OpenAI API key found in key file. "
        "Expected 'OPENAI_API_KEY=sk-...' or a line starting with 'sk-'."
    )


api_key = load_api_key(KEY_FILE)
client = OpenAI(api_key=api_key)

chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
COLLECTION_NAME = "anime_chunks"

try:
    chroma_client.delete_collection(COLLECTION_NAME)
    print(f"Deleted existing collection: {COLLECTION_NAME}")
except Exception:
    pass

collection = chroma_client.create_collection(name=COLLECTION_NAME)


def get_embeddings(texts: list[str]):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts
    )
    return [row.embedding for row in resp.data]


ids = []
documents = []
metadatas = []

count = 0
batch_size = 100

with open(IN_FILE, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue

        item = json.loads(line)
        text = item["text"]
        meta = item.get("metadata", {}) or {}

        ids.append(item["chunk_id"])
        documents.append(text)
        metadatas.append({
            "doc_id": item["doc_id"],
            "entity_type": item["entity_type"],
            "entity_id": str(item["entity_id"]),
            "title": item["title"],
            "section": item["section"],
            "title_ja": meta.get("title_ja", ""),
            "title_cn": meta.get("title_cn", ""),
            "country": meta.get("country", ""),
            "platform": meta.get("platform", ""),
            "studio": meta.get("studio", ""),
            "director": meta.get("director", ""),
        })

        if len(ids) >= batch_size:
            embeddings = get_embeddings(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )
            count += len(ids)
            print(f"Inserted {count} chunks")
            ids, documents, metadatas = [], [], []

if ids:
    embeddings = get_embeddings(documents)
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )
    count += len(ids)

print(f"Done. Total inserted: {count}")
print(f"Chroma DB path: {CHROMA_DIR}")
print(f"Collection count: {collection.count()}")
