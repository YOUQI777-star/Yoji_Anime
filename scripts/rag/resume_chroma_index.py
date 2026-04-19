"""
resume_chroma_index.py
断点续传：只 embed 还不在 anime_chunks collection 里的 chunk，
已有的直接跳过，不重新调用 API。
"""

import json
from pathlib import Path

import chromadb
from openai import OpenAI

ROOT       = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR   = ROOT / "data" / "processed"
CHROMA_DIR = ROOT / "data" / "chroma_db"
IN_FILE    = DATA_DIR / "anime_chunks.jsonl"
KEY_FILE   = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
BATCH_SIZE = 100


def load_api_key(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("sk-"):
        return text
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
        if line.startswith("sk-"):
            return line
    raise ValueError("No valid OpenAI API key found.")


def get_embeddings(client, texts: list[str]) -> list:
    resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [row.embedding for row in resp.data]


def main():
    api_key = load_api_key(KEY_FILE)
    client  = OpenAI(api_key=api_key)

    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection    = chroma_client.get_or_create_collection(name="anime_chunks")

    current_count = collection.count()
    print(f"当前 anime_chunks: {current_count} 条")

    # 读取已有的 chunk_id（分批 get，避免一次拉太多）
    print("读取已有 chunk id...")
    existing_ids: set[str] = set()
    page_size = 5000
    offset    = 0
    while True:
        result = collection.get(limit=page_size, offset=offset, include=[])
        batch_ids = result["ids"]
        if not batch_ids:
            break
        existing_ids.update(batch_ids)
        offset += len(batch_ids)
        print(f"  已读 {len(existing_ids)} 个 id...", end="\r")
    print(f"\n已有 {len(existing_ids)} 个 chunk id")

    # 扫 jsonl，找出还没有的
    all_items = []
    with open(IN_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item["chunk_id"] not in existing_ids:
                all_items.append(item)

    total_todo = len(all_items)
    print(f"还差 {total_todo} 条需要 embed")

    if total_todo == 0:
        print("✅ 已全部完成，无需补充")
        return

    # 批量 embed + upsert
    ids_buf, docs_buf, metas_buf = [], [], []
    done = 0

    for item in all_items:
        meta = item.get("metadata", {}) or {}
        ids_buf.append(item["chunk_id"])
        docs_buf.append(item["text"])
        metas_buf.append({
            "doc_id":      item["doc_id"],
            "entity_type": item["entity_type"],
            "entity_id":   str(item["entity_id"]),
            "title":       item["title"],
            "section":     item["section"],
            "title_ja":    meta.get("title_ja", ""),
            "title_cn":    meta.get("title_cn", ""),
            "country":     meta.get("country", ""),
            "platform":    meta.get("platform", ""),
            "studio":      meta.get("studio", ""),
            "director":    meta.get("director", ""),
        })

        if len(ids_buf) >= BATCH_SIZE:
            embeddings = get_embeddings(client, docs_buf)
            collection.upsert(
                ids=ids_buf,
                documents=docs_buf,
                embeddings=embeddings,
                metadatas=metas_buf,
            )
            done += len(ids_buf)
            print(f"  进度: {done}/{total_todo}  (总计: {current_count + done})", end="\r")
            ids_buf, docs_buf, metas_buf = [], [], []

    # 最后一批
    if ids_buf:
        embeddings = get_embeddings(client, docs_buf)
        collection.upsert(
            ids=ids_buf,
            documents=docs_buf,
            embeddings=embeddings,
            metadatas=metas_buf,
        )
        done += len(ids_buf)

    print(f"\n✅ 补充完成: +{done} 条")
    print(f"anime_chunks 最终总数: {collection.count()}")


if __name__ == "__main__":
    main()
