"""
Compare retrieval quality between:
  - anime_chunks (original, no style)
  - anime_style_seed (style-enhanced, seed only)

Run after both Chroma collections are built.
"""
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
    raise ValueError("No valid OpenAI API key found.")


client = OpenAI(api_key=load_api_key(KEY_FILE))
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

col_original = chroma_client.get_collection("anime_chunks")
col_style = chroma_client.get_collection("anime_style_seed")


def get_embedding(text: str):
    resp = client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


def search(collection, query_embedding, n=5, section_filter=None):
    kwargs = dict(query_embeddings=[query_embedding], n_results=n)
    if section_filter:
        kwargs["where"] = {"section": {"$in": section_filter}}
    return collection.query(**kwargs)


def print_results(label, results, n=5):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for i, (doc, meta) in enumerate(zip(
            results["documents"][0][:n], results["metadatas"][0][:n]), 1):
        print(f"\n[{i}] {meta.get('title', '')}  ({meta.get('section', '')})")
        snippet = doc[:200].replace("\n", " ")
        print(f"    {snippet}...")


QUERIES = [
    "我想看压抑一点、带政治冲突和战争感的动画",
    "我想看安静、克制、余韵很强的作品",
    "我想看轻松可爱、适合社恐共鸣的番",
    "我想看高燃、情绪爆发强的热血作品",
]

for query in QUERIES:
    print(f"\n\n{'#'*70}")
    print(f"QUERY: {query}")
    print(f"{'#'*70}")

    emb = get_embedding(query)

    # Original collection — filter to summary/overview only to reduce tag noise
    res_orig = search(col_original, emb, n=5,
                      section_filter=["summary", "overview"])
    print_results("Original collection (summary/overview only)", res_orig)

    # Style-enhanced mini collection — all sections
    res_style = search(col_style, emb, n=5)
    print_results("Style-seed collection (all sections)", res_style)
