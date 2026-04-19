"""
Build a mini Chroma collection containing only the style-seed anime chunks.
Collection name: anime_style_seed

Run after build_anime_chunks_with_style.py has produced anime_chunks_with_style.jsonl.
"""
import json
from pathlib import Path

import chromadb
from openai import OpenAI

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
CHROMA_DIR = ROOT / "data" / "chroma_db"
IN_FILE = DATA_DIR / "anime_chunks_with_style.jsonl"
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
COLLECTION_NAME = "anime_style_seed"


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
    raise ValueError("No valid OpenAI API key found in key file.")


client = OpenAI(api_key=load_api_key(KEY_FILE))
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

# Delete existing collection if present so we get a clean rebuild
try:
    chroma_client.delete_collection(COLLECTION_NAME)
    print(f"Deleted existing collection: {COLLECTION_NAME}")
except Exception:
    pass

collection = chroma_client.create_collection(name=COLLECTION_NAME)


def get_embedding(text: str):
    resp = client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


ids, documents, embeddings, metadatas = [], [], [], []
count = 0
skipped = 0

with open(IN_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue

        item = json.loads(line)
        meta = item.get("metadata", {}) or {}

        # Only include chunks from style-seed anime (those that have mood set)
        if not meta.get("mood"):
            skipped += 1
            continue

        text = item["text"]
        embedding = get_embedding(text)

        ids.append(item["chunk_id"])
        documents.append(text)
        embeddings.append(embedding)
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
            "mood": meta.get("mood", ""),
            "themes": meta.get("themes", ""),
            "tone": meta.get("tone", ""),
            "pace": meta.get("pace", ""),
            "audience": meta.get("audience", ""),
        })

        # Flush in batches of 50 (small collection — no need for large batches)
        if len(ids) >= 50:
            collection.upsert(ids=ids, documents=documents,
                              embeddings=embeddings, metadatas=metadatas)
            count += len(ids)
            print(f"Inserted {count} chunks")
            ids, documents, embeddings, metadatas = [], [], [], []

if ids:
    collection.upsert(ids=ids, documents=documents,
                      embeddings=embeddings, metadatas=metadatas)
    count += len(ids)

print(f"Done. Inserted: {count}  Skipped (no style): {skipped}")
print(f"Chroma DB path: {CHROMA_DIR}")
print(f"Collection '{COLLECTION_NAME}' count: {collection.count()}")
