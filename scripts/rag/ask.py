"""
Minimal /ask QA CLI.

Usage:
    python scripts/rag/ask.py "这部番讲什么？Code Geass"
    python scripts/rag/ask.py  # interactive mode

Retrieves top chunks from anime_chunks (and optionally anime_style_seed)
then calls GPT to produce an answer.
"""
import json
import sys
from pathlib import Path

import chromadb
from openai import OpenAI

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
CHROMA_DIR = ROOT / "data" / "chroma_db"
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"

TOP_K = 8          # chunks to retrieve
MAX_CTX_CHARS = 4000  # rough context limit before sending to LLM
LLM_MODEL = "gpt-4o-mini"


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

col_main = chroma_client.get_collection("anime_chunks")

# Style collection is optional — gracefully skip if not built yet
try:
    col_style = chroma_client.get_collection("anime_style_seed")
except Exception:
    col_style = None


def get_embedding(text: str):
    resp = client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


def retrieve(query: str) -> list[dict]:
    emb = get_embedding(query)
    chunks = []

    # Main collection: prefer summary + overview, then open search
    for section_filter in [["summary", "overview", "tags"], None]:
        kwargs = dict(query_embeddings=[emb], n_results=TOP_K)
        if section_filter:
            kwargs["where"] = {"section": {"$in": section_filter}}
        res = col_main.query(**kwargs)
        for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
            chunks.append({"text": doc, "meta": meta})
        if chunks:
            break

    # Augment with style collection if available
    if col_style:
        res2 = col_style.query(query_embeddings=[emb], n_results=4)
        for doc, meta in zip(res2["documents"][0], res2["metadatas"][0]):
            chunks.append({"text": doc, "meta": meta, "source": "style"})

    # Deduplicate by text prefix
    seen = set()
    unique = []
    for c in chunks:
        key = c["text"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique[:TOP_K + 4]


def build_context(chunks: list[dict]) -> str:
    parts = []
    total = 0
    for c in chunks:
        title = c["meta"].get("title", "")
        section = c["meta"].get("section", "")
        text = c["text"]
        block = f"[{title} / {section}]\n{text}"
        if total + len(block) > MAX_CTX_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


SYSTEM_PROMPT = """你是 Yoji Anime 的动漫知识助手，擅长根据数据库信息回答关于动画的问题。
请根据下方检索到的参考内容来回答用户的问题。
- 如果参考内容足够，直接基于内容回答，不要编造。
- 如果参考内容不足，诚实说明你没有足够信息，但可以给出合理推测并注明。
- 回答尽量简洁，300字以内，除非用户明确要求详细。
- 如果是推荐请求，列出推荐理由。
"""


def ask(query: str) -> str:
    chunks = retrieve(query)
    context = build_context(chunks)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"参考内容：\n\n{context}\n\n---\n\n问题：{query}"},
    ]

    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=600,
    )
    return resp.choices[0].message.content.strip()


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"\nQ: {query}\n")
        print(ask(query))
    else:
        print("Yoji Anime Ask  (输入 q 退出)")
        while True:
            try:
                query = input("\nQ: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if query.lower() in ("q", "quit", "exit", ""):
                break
            print("\nA:", ask(query))


if __name__ == "__main__":
    main()
