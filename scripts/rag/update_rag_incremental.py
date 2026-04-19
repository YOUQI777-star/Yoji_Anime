import argparse
import json
import math
import os
from pathlib import Path

import chromadb
from neo4j import GraphDatabase
from openai import OpenAI


ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
DOCS_FILE = DATA_DIR / "anime_docs.jsonl"
CHUNKS_FILE = DATA_DIR / "anime_chunks.jsonl"
CHROMA_DIR = ROOT / "data" / "chroma_db"
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
COLLECTION_NAME = "anime_chunks"
EMBED_MODEL = "text-embedding-3-small"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Incrementally append missing anime docs/chunks and embed only new Chroma entries."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect diffs and counts without writing files or Chroma.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process the first N missing anime IDs (0 = all).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Embedding upsert batch size.",
    )
    parser.add_argument(
        "--include-no-summary",
        action="store_true",
        help="Include anime even if summary is empty. Default behavior matches the current gap analysis and only includes anime with a summary.",
    )
    return parser.parse_args()


def load_api_key(path: Path) -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key

    if not path.exists():
        raise FileNotFoundError(f"Key file not found: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("sk-"):
        return text

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("OPENAI_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
        if line.startswith("sk-"):
            return line

    raise ValueError("No valid OpenAI API key found in env or key file.")


def load_neo4j_config(path: Path) -> dict:
    cfg = {
        "NEO4J_URI": os.getenv("NEO4J_URI", "").strip(),
        "NEO4J_USER": os.getenv("NEO4J_USER", "").strip() or "neo4j",
        "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD", "").strip(),
        "NEO4J_DATABASE": os.getenv("NEO4J_DATABASE", "").strip() or "neo4j",
    }
    if cfg["NEO4J_URI"] and cfg["NEO4J_PASSWORD"]:
        return cfg

    if not path.exists():
        raise FileNotFoundError(f"Neo4j config file not found: {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in {"NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE", "NEO4J_USERNAME"}:
            if k == "NEO4J_USERNAME":
                cfg["NEO4J_USER"] = v or cfg["NEO4J_USER"]
            else:
                cfg[k] = v or cfg.get(k, "")

    if not cfg["NEO4J_URI"] or not cfg["NEO4J_PASSWORD"]:
        raise ValueError("Missing Neo4j credentials in env or key file.")

    return cfg


def safe_str(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def safe_num(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def unique_keep_order(values):
    seen = set()
    out = []
    for value in values or []:
        s = safe_str(value)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def top_n(values, n=10):
    return unique_keep_order(values)[:n]


def compact_list(values, limit=10, drop_values=None):
    drop_values = set(drop_values or [])
    result = []
    seen = set()
    for v in values or []:
        s = safe_str(v)
        if not s or s in seen or s in drop_values:
            continue
        seen.add(s)
        result.append(s)
        if len(result) >= limit:
            break
    return result


def build_doc_text(record):
    title = safe_str(record["title"])
    title_ja = safe_str(record["title_ja"])
    title_cn = safe_str(record["title_cn"])
    date = safe_str(record["date"])
    country = safe_str(record["country"])
    platform = safe_str(record["platform"])
    studio = safe_str(record["studio"])
    director = safe_str(record["director"])
    summary = safe_str(record["summary"])

    score = safe_num(record["score"])
    rank = safe_num(record["rank"])
    episodes = safe_num(record["episodes"])

    tags = top_n(record.get("tags", []), 12)
    characters = top_n(record.get("characters", []), 10)
    voice_actors = top_n(record.get("voice_actors", []), 10)
    related = top_n(record.get("related_works", []), 10)

    parts = []

    basic = f"作品名：{title}。"
    if title_ja and title_ja != title:
        basic += f" 日文名：{title_ja}。"
    if title_cn and title_cn != title:
        basic += f" 中文名：{title_cn}。"
    if country:
        basic += f" 国家/地区：{country}。"
    if platform:
        basic += f" 播出形式：{platform}。"
    if date:
        basic += f" 首播时间：{date}。"
    if episodes is not None:
        episode_num = int(episodes) if isinstance(episodes, float) and episodes.is_integer() else episodes
        basic += f" 集数：{episode_num}。"
    if studio:
        basic += f" 制作公司：{studio}。"
    if director:
        basic += f" 导演：{director}。"
    if score is not None:
        basic += f" 评分：{score}。"
    if rank is not None:
        rank_num = int(rank) if isinstance(rank, float) and rank.is_integer() else rank
        basic += f" 排名：{rank_num}。"
    parts.append(basic)

    if summary:
        parts.append(f"剧情简介：{summary}")
    if tags:
        parts.append("标签：" + "、".join(tags) + "。")
    if characters:
        parts.append("主要角色：" + "、".join(characters) + "。")
    if voice_actors:
        parts.append("相关声优：" + "、".join(voice_actors) + "。")
    if related:
        parts.append("关联作品：" + "、".join(related) + "。")

    return "\n".join(parts), tags, characters, voice_actors, related


def build_doc(record):
    text, tags, characters, voice_actors, related = build_doc_text(record)
    entity_id = int(record["anime_id"])
    rank = safe_num(record["rank"])
    episodes = safe_num(record["episodes"])

    return {
        "doc_id": f"anime_{entity_id}",
        "entity_type": "Anime",
        "entity_id": entity_id,
        "title": safe_str(record["title"]),
        "title_ja": safe_str(record["title_ja"]),
        "title_cn": safe_str(record["title_cn"]),
        "metadata": {
            "date": safe_str(record["date"]),
            "country": safe_str(record["country"]),
            "platform": safe_str(record["platform"]),
            "score": None if safe_num(record["score"]) is None else float(record["score"]),
            "rank": None if rank is None else int(rank) if isinstance(rank, float) and rank.is_integer() else rank,
            "episodes": None if episodes is None else float(episodes),
            "studio": safe_str(record["studio"]),
            "director": safe_str(record["director"]),
            "tags": tags,
            "characters": characters,
            "voice_actors": voice_actors,
            "related_works": related,
        },
        "text": text,
    }


def make_chunk(doc, section, text):
    meta = doc.get("metadata", {}) or {}
    return {
        "chunk_id": f"{doc['doc_id']}_{section}",
        "doc_id": doc["doc_id"],
        "entity_type": doc["entity_type"],
        "entity_id": doc["entity_id"],
        "title": doc["title"],
        "section": section,
        "text": text.strip(),
        "metadata": {
            "title_ja": doc.get("title_ja", ""),
            "title_cn": doc.get("title_cn", ""),
            "date": meta.get("date", ""),
            "country": meta.get("country", ""),
            "platform": meta.get("platform", ""),
            "score": meta.get("score"),
            "rank": meta.get("rank"),
            "episodes": meta.get("episodes"),
            "studio": meta.get("studio", ""),
            "director": meta.get("director", ""),
            "tags": compact_list(meta.get("tags", []), limit=12, drop_values={"TV"}),
            "characters": compact_list(meta.get("characters", []), limit=10),
            "voice_actors": compact_list(meta.get("voice_actors", []), limit=10),
            "related_works": compact_list(meta.get("related_works", []), limit=10),
        },
    }


def build_chunks_from_doc(doc):
    meta = doc.get("metadata", {}) or {}
    title = safe_str(doc.get("title"))
    title_ja = safe_str(doc.get("title_ja"))
    title_cn = safe_str(doc.get("title_cn"))

    date = safe_str(meta.get("date"))
    country = safe_str(meta.get("country"))
    platform = safe_str(meta.get("platform"))
    studio = safe_str(meta.get("studio"))
    director = safe_str(meta.get("director"))
    score = meta.get("score")
    rank = meta.get("rank")
    episodes = meta.get("episodes")

    full_text = doc.get("text", "")
    parts = [p.strip() for p in full_text.split("\n") if p.strip()]
    part_map = {}

    for p in parts:
        if p.startswith("作品名："):
            part_map["overview"] = p
        elif p.startswith("剧情简介："):
            part_map["summary"] = p
        elif p.startswith("标签："):
            part_map["tags"] = p
        elif p.startswith("主要角色："):
            part_map["characters"] = p
        elif p.startswith("相关声优："):
            part_map["voice_actors"] = p
        elif p.startswith("关联作品："):
            part_map["related_works"] = p

    overview_text = part_map.get("overview")
    if not overview_text:
        bits = [f"作品名：{title}。"]
        if title_ja and title_ja != title:
            bits.append(f"日文名：{title_ja}。")
        if title_cn and title_cn != title:
            bits.append(f"中文名：{title_cn}。")
        if country:
            bits.append(f"国家/地区：{country}。")
        if platform:
            bits.append(f"播出形式：{platform}。")
        if date:
            bits.append(f"首播时间：{date}。")
        if episodes not in [None, ""]:
            bits.append(f"集数：{episodes}。")
        if studio:
            bits.append(f"制作公司：{studio}。")
        if director:
            bits.append(f"导演：{director}。")
        if score not in [None, ""]:
            bits.append(f"评分：{score}。")
        if rank not in [None, ""]:
            bits.append(f"排名：{rank}。")
        overview_text = " ".join(bits)

    chunk_candidates = [
        ("overview", overview_text),
        ("summary", part_map.get("summary", "")),
        ("tags", part_map.get("tags", "")),
        ("characters", part_map.get("characters", "")),
        ("voice_actors", part_map.get("voice_actors", "")),
        ("related_works", part_map.get("related_works", "")),
    ]

    chunks = []
    for section, text in chunk_candidates:
        if text and text.strip():
            chunks.append(make_chunk(doc, section, text))
    return chunks


def read_existing_doc_ids(path: Path):
    ids = set()
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            ids.add(item["doc_id"])
    return ids


def read_existing_chunk_ids(path: Path):
    ids = set()
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            ids.add(item["chunk_id"])
    return ids


def read_chunks_by_ids(path: Path, wanted_ids):
    wanted_ids = set(wanted_ids)
    chunks = []
    if not wanted_ids:
        return chunks
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item["chunk_id"] in wanted_ids:
                chunks.append(item)
    return chunks


def fetch_existing_chroma_ids(collection, ids, batch_size=200):
    found = set()
    ids = list(ids)
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        res = collection.get(ids=batch)
        for chunk_id in res.get("ids", []) or []:
            found.add(chunk_id)
    return found


def append_jsonl(path: Path, items):
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def fetch_candidate_records(driver, database, include_no_summary=False):
    summary_filter = "" if include_no_summary else "AND trim(coalesce(a.summary, '')) <> ''"
    query = f"""
    MATCH (a:Anime)
    WHERE a.id IS NOT NULL {summary_filter}
    OPTIONAL MATCH (a)-[:HAS_TAG]->(t:Tag)
    OPTIONAL MATCH (a)-[:HAS_CHARACTER]->(c:Character)
    OPTIONAL MATCH (c)-[:VOICED_BY]->(v:VoiceActor)
    OPTIONAL MATCH (a)-[r:RELATED_TO]-(rel:Anime)
    WHERE rel.id IS NOT NULL
    RETURN
      a.id AS anime_id,
      coalesce(a.name_cn, a.name) AS title,
      coalesce(a.name, '') AS title_ja,
      coalesce(a.name_cn, '') AS title_cn,
      coalesce(a.date, '') AS date,
      coalesce(a.country, '') AS country,
      coalesce(a.platform, '') AS platform,
      coalesce(a.studio, '') AS studio,
      coalesce(a.director, '') AS director,
      coalesce(a.summary, '') AS summary,
      a.score AS score,
      a.rank AS rank,
      a.episodes AS episodes,
      [x IN collect(DISTINCT t.name) WHERE x IS NOT NULL AND trim(x) <> ''] AS tags,
      [x IN collect(DISTINCT c.name_cn) WHERE x IS NOT NULL AND trim(x) <> ''] AS characters,
      [x IN collect(DISTINCT v.name) WHERE x IS NOT NULL AND trim(x) <> ''] AS voice_actors,
      [x IN collect(DISTINCT coalesce(rel.name_cn, rel.name)) WHERE x IS NOT NULL AND trim(x) <> ''] AS related_works
    ORDER BY anime_id
    """
    with driver.session(database=database) as session:
        return [row.data() for row in session.run(query)]


def get_embeddings(client, texts):
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [row.embedding for row in resp.data]


def upsert_chunks_to_chroma(collection, client, chunks, batch_size=100):
    ids = []
    documents = []
    metadatas = []
    inserted = 0

    for chunk in chunks:
        meta = chunk.get("metadata", {}) or {}
        ids.append(chunk["chunk_id"])
        documents.append(chunk["text"])
        metadatas.append({
            "doc_id": chunk["doc_id"],
            "entity_type": chunk["entity_type"],
            "entity_id": str(chunk["entity_id"]),
            "title": chunk["title"],
            "section": chunk["section"],
            "title_ja": meta.get("title_ja", ""),
            "title_cn": meta.get("title_cn", ""),
            "country": meta.get("country", ""),
            "platform": meta.get("platform", ""),
            "studio": meta.get("studio", ""),
            "director": meta.get("director", ""),
        })

        if len(ids) >= batch_size:
            embeddings = get_embeddings(client, documents)
            collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
            inserted += len(ids)
            print(f"[chroma] upserted {inserted} chunks")
            ids, documents, metadatas = [], [], []

    if ids:
        embeddings = get_embeddings(client, documents)
        collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        inserted += len(ids)
        print(f"[chroma] upserted {inserted} chunks")

    return inserted


def main():
    args = parse_args()

    neo4j_cfg = load_neo4j_config(KEY_FILE)
    driver = GraphDatabase.driver(
        neo4j_cfg["NEO4J_URI"],
        auth=(neo4j_cfg["NEO4J_USER"], neo4j_cfg["NEO4J_PASSWORD"]),
    )

    print("[scan] loading existing docs/chunks...")
    existing_doc_ids = read_existing_doc_ids(DOCS_FILE)
    existing_chunk_ids = read_existing_chunk_ids(CHUNKS_FILE)
    print(f"[scan] existing docs: {len(existing_doc_ids)}")
    print(f"[scan] existing chunks in jsonl: {len(existing_chunk_ids)}")

    print("[neo4j] fetching current anime candidates...")
    records = fetch_candidate_records(
        driver=driver,
        database=neo4j_cfg["NEO4J_DATABASE"],
        include_no_summary=args.include_no_summary,
    )
    driver.close()
    print(f"[neo4j] candidates: {len(records)}")

    candidate_doc_ids = set()
    missing_records = []
    for record in records:
        doc_id = f"anime_{int(record['anime_id'])}"
        candidate_doc_ids.add(doc_id)
        if doc_id not in existing_doc_ids:
            missing_records.append(record)

    if args.limit > 0:
        missing_records = missing_records[:args.limit]

    print(f"[diff] missing docs to append: {len(missing_records)}")
    print(f"[diff] existing docs overlapping current neo4j candidates: {len(existing_doc_ids & candidate_doc_ids)}")
    if missing_records:
        preview_ids = [int(r["anime_id"]) for r in missing_records[:10]]
        print(f"[diff] first anime_ids: {preview_ids}")

    new_docs = [build_doc(record) for record in missing_records]
    new_chunks_all = []
    for doc in new_docs:
        new_chunks_all.extend(build_chunks_from_doc(doc))

    chunks_to_append = [c for c in new_chunks_all if c["chunk_id"] not in existing_chunk_ids]
    print(f"[diff] new chunks to append into jsonl: {len(chunks_to_append)}")

    api_key = load_api_key(KEY_FILE)
    client = OpenAI(api_key=api_key)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

    if args.dry_run:
        desired_chunk_ids = [chunk["chunk_id"] for chunk in chunks_to_append]
        existing_chroma_ids = fetch_existing_chroma_ids(collection, desired_chunk_ids)
        chunks_to_embed = [chunk for chunk in chunks_to_append if chunk["chunk_id"] not in existing_chroma_ids]
        print(f"[chroma] collection count before: {collection.count()}")
        print(f"[chroma] chunks already present in collection: {len(existing_chroma_ids)}")
        print(f"[chroma] chunks needing embedding/upsert: {len(chunks_to_embed)}")
        print("[dry-run] no files or chroma collections were modified.")
        return

    append_jsonl(DOCS_FILE, new_docs)
    append_jsonl(CHUNKS_FILE, chunks_to_append)
    print(f"[write] appended docs: {len(new_docs)} -> {DOCS_FILE}")
    print(f"[write] appended chunks: {len(chunks_to_append)} -> {CHUNKS_FILE}")

    all_chunk_ids = read_existing_chunk_ids(CHUNKS_FILE)
    existing_chroma_ids = fetch_existing_chroma_ids(collection, all_chunk_ids)
    missing_chroma_ids = all_chunk_ids - existing_chroma_ids
    chunks_to_embed = read_chunks_by_ids(CHUNKS_FILE, missing_chroma_ids)

    print(f"[chroma] collection count before sync: {collection.count()}")
    print(f"[chroma] total chunks in jsonl: {len(all_chunk_ids)}")
    print(f"[chroma] chunks already present in collection: {len(existing_chroma_ids)}")
    print(f"[chroma] chunks needing embedding/upsert: {len(chunks_to_embed)}")

    inserted = 0
    if chunks_to_embed:
        inserted = upsert_chunks_to_chroma(
            collection=collection,
            client=client,
            chunks=chunks_to_embed,
            batch_size=max(1, args.batch_size),
        )

    print(f"[done] docs appended: {len(new_docs)}")
    print(f"[done] chunks appended to jsonl: {len(chunks_to_append)}")
    print(f"[done] chunks embedded/upserted: {inserted}")
    print(f"[done] chroma count after: {collection.count()}")


if __name__ == "__main__":
    main()
