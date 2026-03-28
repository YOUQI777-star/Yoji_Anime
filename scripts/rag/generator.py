"""
Generator — 混合 RAG 最终答案生成器
整合 intent 分类 + hybrid retrieval + GPT 生成

用法：
    from scripts.rag.generator import answer
    print(answer("推荐几部和进击的巨人类似的番"))

    # CLI
    python scripts/rag/generator.py "花澤香菜配过哪些动画？"
    python scripts/rag/generator.py   # 交互模式
"""

import os
import sys
from pathlib import Path

# 路径修正（本地和容器均正确）
ROOT = Path(os.getenv("PROJECT_ROOT", str(Path(__file__).parent.parent.parent)))
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from scripts.rag.intent import classify
from scripts.rag.retriever import retrieve

# ─────────────────────────── 配置 ─────────────────────────────
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"

LLM_MODEL     = "gpt-4o-mini"
MAX_CTX_CHARS = 5000
MAX_TOKENS    = 700


def _load_api_key(key_file: Path) -> str:
    """优先读环境变量，fallback 到本地密钥文件。"""
    key = os.getenv("OPENAI_API_KEY", "")
    if key:
        return key
    if key_file.exists():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError("OPENAI_API_KEY not found in env or key file")


_client = OpenAI(api_key=_load_api_key(KEY_FILE))


# ─────────────────────────── Prompt 模板 ──────────────────────
_SYSTEM = {
    "factual": """你是 Yoji Anime 的动漫知识助手。
请严格基于下方检索内容回答用户的事实性问题。
- 如果检索内容已覆盖答案，直接回答，不要编造。
- 如果检索内容不足（例如没有找到对应作品），诚实告知"数据库中暂无该番的详细信息"，并给出简短合理推测（注明是推测）。
- 回答尽量简洁，300字以内。""",

    "recommend": """你是 Yoji Anime 的动漫推荐助手。
请基于下方检索内容，为用户推荐最符合需求的动画作品。
- 每部作品给出：名称、简短推荐理由（结合风格/评分/题材）。
- 推荐 3~5 部，按相关度排序。
- 如果检索内容包含 style_profile（风格描述），优先引用。
- 不要编造未在检索内容中出现的作品。""",

    "relation": """你是 Yoji Anime 的动漫关系查询助手。
请基于下方检索内容（可能包含图数据库的关系结果），回答用户的关联查询。
- 声优查询：列出该声优配过的作品及角色名。
- 系列查询：列出系列各部作品及关系类型（续集/前传/衍生等）。
- 其他关系：根据内容如实列出，注明数据来源。
- 如果检索内容不足，诚实告知。""",
}


# ─────────────────────────── context 构建 ─────────────────────
def _build_context(blocks: list[dict]) -> str:
    parts = []
    total = 0
    for b in blocks:
        src     = b.get("source", "")
        title   = b.get("title", "")
        section = b.get("section", "")
        text    = b.get("text", "")
        score   = b.get("score")

        score_str = f"  评分={score}" if score and isinstance(score, (int, float)) else ""
        header = f"[{src}/{section}] 《{title}》{score_str}"
        block  = f"{header}\n{text}"

        if total + len(block) > MAX_CTX_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


# ─────────────────────────── 主函数 ───────────────────────────
def answer(query: str, verbose: bool = False) -> str:
    cls    = classify(query)
    intent = cls["intent"]
    blocks = retrieve(query)

    if verbose:
        print(f"[intent={intent}  blocks={len(blocks)}]")
        for b in blocks[:4]:
            print(f"  [{b['source']}/{b['section']}] {b['title']}")

    context  = _build_context(blocks)
    sys_prompt = _SYSTEM[intent]

    messages = [
        {"role": "system",  "content": sys_prompt},
        {"role": "user",    "content": f"参考内容：\n\n{context}\n\n---\n\n问题：{query}"},
    ]

    resp = _client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=MAX_TOKENS,
    )
    return resp.choices[0].message.content.strip()


# ─────────────────────────── CLI ──────────────────────────────
def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    args    = [a for a in sys.argv[1:] if not a.startswith("-")]

    if args:
        query = " ".join(args)
        print(f"\nQ: {query}\n")
        print(answer(query, verbose=verbose))
    else:
        print("Yoji Anime (输入 q 退出，--verbose 显示检索信息)")
        while True:
            try:
                query = input("\nQ: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if query.lower() in ("q", "quit", "exit", ""):
                break
            print("\nA:", answer(query, verbose=verbose))


if __name__ == "__main__":
    main()
