import argparse
import json
import math
import os
from pathlib import Path

import chromadb
from neo4j import GraphDatabase


ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
DOCS_FILE = DATA_DIR / "anime_docs.jsonl"
CHUNKS_FILE = DATA_DIR / "anime_chunks.jsonl"
CHROMA_DIR = ROOT / "data" / "chroma_db"
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
COLLECTION_NAME = "anime_chunks"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check whether Neo4j, docs, chunks, and Chroma are in sync for the RAG pipeline."
    )
    parser.add_argument(
        "--include-no-summary",
        action="store_true",
        help="Check all Anime nodes, not just those with non-empty summaries.",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="How many missing IDs/chunks to print per category.",
    )
    parser.add_argument(
        "--deep-chroma-check",
        action="store_true",
        help="Check chunk existence in Chroma by id. Slower and heavier than the default count-based check.",
    )
    return parser.parse_args()


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


def read_doc_ids(path: Path):
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


def read_docs(path: Path):
    docs = []
    if not path.exists():
        return docs
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            docs.append(json.loads(line))
    return docs


def read_chunk_ids(path: Path):
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


def fetch_candidate_doc_ids(driver, database, include_no_summary=False):
    summary_filter = "" if include_no_summary else "AND trim(coalesce(a.summary, '')) <> ''"
    query = f"""
    MATCH (a:Anime)
    WHERE a.id IS NOT NULL {summary_filter}
    RETURN a.id AS anime_id
    ORDER BY anime_id
    """
    with driver.session(database=database) as session:
        return {f"anime_{int(row['anime_id'])}" for row in session.run(query)}


def expected_chunk_ids_from_docs(docs, active_doc_ids):
    chunk_ids = set()
    for doc in docs:
        doc_id = doc["doc_id"]
        if doc_id not in active_doc_ids:
            continue
        full_text = (doc.get("text") or "").strip()
        parts = [p.strip() for p in full_text.split("\n") if p.strip()]
        seen_sections = set()

        for p in parts:
            if p.startswith("作品名："):
                seen_sections.add("overview")
            elif p.startswith("剧情简介："):
                seen_sections.add("summary")
            elif p.startswith("标签："):
                seen_sections.add("tags")
            elif p.startswith("主要角色："):
                seen_sections.add("characters")
            elif p.startswith("相关声优："):
                seen_sections.add("voice_actors")
            elif p.startswith("关联作品："):
                seen_sections.add("related_works")

        # build_anime_chunks.py always guarantees an overview chunk
        seen_sections.add("overview")

        for section in seen_sections:
            chunk_ids.add(f"{doc_id}_{section}")
    return chunk_ids


def fetch_existing_chroma_ids(collection, ids, batch_size=200):
    found = set()
    ids = list(ids)
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        res = collection.get(ids=batch)
        for chunk_id in res.get("ids", []) or []:
            found.add(chunk_id)
    return found


def sample_sorted(values, n):
    def sort_key(v):
        text = str(v)
        if text.startswith("anime_"):
            tail = text[6:]
            if tail.isdigit():
                return (0, int(tail))
        if "_overview" in text or "_summary" in text:
            return (1, text)
        return (2, text)

    return sorted(values, key=sort_key)[:n]


def extract_doc_id_from_chunk_id(chunk_id):
    suffixes = (
        "_overview",
        "_summary",
        "_tags",
        "_characters",
        "_voice_actors",
        "_related_works",
    )
    for suffix in suffixes:
        if chunk_id.endswith(suffix):
            return chunk_id[: -len(suffix)]
    return None


def main():
    args = parse_args()

    cfg = load_neo4j_config(KEY_FILE)
    driver = GraphDatabase.driver(
        cfg["NEO4J_URI"],
        auth=(cfg["NEO4J_USER"], cfg["NEO4J_PASSWORD"]),
    )
    try:
        neo4j_doc_ids = fetch_candidate_doc_ids(
            driver=driver,
            database=cfg["NEO4J_DATABASE"],
            include_no_summary=args.include_no_summary,
        )
    finally:
        driver.close()

    docs = read_docs(DOCS_FILE)
    docs_doc_ids = {doc["doc_id"] for doc in docs}
    chunk_ids = read_chunk_ids(CHUNKS_FILE)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

    docs_overlap = neo4j_doc_ids & docs_doc_ids
    docs_missing_from_jsonl = neo4j_doc_ids - docs_doc_ids
    docs_extra_in_jsonl = docs_doc_ids - neo4j_doc_ids

    expected_chunk_prefixes = expected_chunk_ids_from_docs(docs, neo4j_doc_ids)
    chunk_ids_for_current_docs = set()
    for chunk_id in chunk_ids:
        doc_id = extract_doc_id_from_chunk_id(chunk_id)
        if doc_id in neo4j_doc_ids:
            chunk_ids_for_current_docs.add(chunk_id)
    chunks_missing_from_jsonl = expected_chunk_prefixes - chunk_ids_for_current_docs
    extra_chunks_in_jsonl = chunk_ids_for_current_docs - expected_chunk_prefixes

    chroma_count = collection.count()
    chunks_missing_from_chroma = set()
    extra_chunks_in_chroma_vs_jsonl = chroma_count - len(chunk_ids)
    if args.deep_chroma_check:
        chroma_existing_for_jsonl = fetch_existing_chroma_ids(collection, chunk_ids)
        chunks_missing_from_chroma = chunk_ids - chroma_existing_for_jsonl
        extra_chunks_in_chroma_vs_jsonl = chroma_count - len(chroma_existing_for_jsonl)

    print("=== RAG Sync Check ===")
    print(f"Neo4j candidate docs: {len(neo4j_doc_ids)}")
    print(f"Docs jsonl doc_ids: {len(docs_doc_ids)}")
    print(f"Chunks jsonl chunk_ids: {len(chunk_ids)}")
    print(f"Chroma collection count: {chroma_count}")
    print()
    print(f"Docs overlap (Neo4j ∩ docs): {len(docs_overlap)}")
    print(f"Docs missing from jsonl: {len(docs_missing_from_jsonl)}")
    print(f"Docs extra in jsonl: {len(docs_extra_in_jsonl)}")
    print(f"Expected chunk ids for current Neo4j docs: {len(expected_chunk_prefixes)}")
    print(f"Chunks missing from jsonl: {len(chunks_missing_from_jsonl)}")
    print(f"Extra chunks in jsonl for current docs: {len(extra_chunks_in_jsonl)}")
    if args.deep_chroma_check:
        print(f"Chunks missing from Chroma: {len(chunks_missing_from_chroma)}")
    else:
        print(f"Chunks missing from Chroma: count check not run (use --deep-chroma-check for full verification)")
    print(f"Extra entries in Chroma vs jsonl lookup set: {extra_chunks_in_chroma_vs_jsonl}")

    if docs_missing_from_jsonl:
        print()
        print("Sample docs missing from jsonl:")
        for item in sample_sorted(docs_missing_from_jsonl, args.sample):
            print(f"- {item}")

    if docs_extra_in_jsonl:
        print()
        print("Sample docs extra in jsonl:")
        for item in sample_sorted(docs_extra_in_jsonl, args.sample):
            print(f"- {item}")

    if chunks_missing_from_jsonl:
        print()
        print("Sample chunks missing from jsonl:")
        for item in sample_sorted(chunks_missing_from_jsonl, args.sample):
            print(f"- {item}")

    if chunks_missing_from_chroma:
        print()
        print("Sample chunks missing from Chroma:")
        for item in sample_sorted(chunks_missing_from_chroma, args.sample):
            print(f"- {item}")

    ok = (
        not docs_missing_from_jsonl
        and not chunks_missing_from_jsonl
        and extra_chunks_in_chroma_vs_jsonl == 0
        and (not args.deep_chroma_check or not chunks_missing_from_chroma)
    )

    print()
    print("STATUS: OK" if ok else "STATUS: DRIFT DETECTED")


if __name__ == "__main__":
    main()
