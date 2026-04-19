"""
Hybrid Retriever
根据 intent 混合调用 ChromaDB 向量检索 + Neo4j 图检索，返回统一格式的 context blocks。

调用方式：
    from scripts.rag.retriever import retrieve
    blocks = retrieve("推荐和进击的巨人类似的番")

每个 block:
    {
        "source": "vector" | "graph",
        "title":  str,
        "section": str,
        "text":   str,
        "score":  float | None,   # 向量距离 / 图评分
        "meta":   dict,
    }
"""

import os
import re
import sys
from pathlib import Path

import chromadb
from neo4j import GraphDatabase
from openai import OpenAI

# ─────────────────────────── 路径 ─────────────────────────────
# __file__ 相对推导，本地和容器均正确
#   本地:  .../Yoji_Anime/scripts/rag/retriever.py → parent×3 = Yoji_Anime/
#   容器:  /app/scripts/rag/retriever.py           → parent×3 = /app/
ROOT       = Path(os.getenv("PROJECT_ROOT", str(Path(__file__).parent.parent.parent)))
CHROMA_DIR = Path(os.getenv("CHROMA_DIR",  str(ROOT / "data" / "chroma_db")))
KEY_FILE   = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"

sys.path.insert(0, str(ROOT))
from scripts.rag.intent import classify

TOP_K_VEC   = 8    # 向量检索条数
TOP_K_GRAPH = 6    # 图检索条数
MIN_VEC_SCORE = 0.15  # 向量检索最低相关性阈值：过滤负分及明显无关结果，保留语义相近条目


# ─────────────────────────── 连接初始化 ───────────────────────
def _load_config(key_file: Path) -> dict:
    """优先读环境变量，fallback 到本地密钥文件（本地开发用）。"""
    cfg = {
        "NEO4J_URI":      os.getenv("NEO4J_URI", ""),
        "NEO4J_USERNAME": os.getenv("NEO4J_USER", "neo4j"),
        "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD", ""),
        "NEO4J_DATABASE": os.getenv("NEO4J_DATABASE", "neo4j"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
    }
    # 环境变量未配置时，fallback 到本地文件
    if not cfg["NEO4J_URI"] and key_file.exists():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


_cfg = _load_config(KEY_FILE)
_oai = OpenAI(api_key=_cfg["OPENAI_API_KEY"])

# Chroma：可选。目录不存在时降级为图检索
_chroma    = None
_col_main  = None
_col_style = None
if CHROMA_DIR.exists():
    try:
        _chroma   = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _col_main = _chroma.get_collection("anime_chunks")
        try:
            _col_style = _chroma.get_collection("anime_style_seed")
        except Exception:
            _col_style = None
        print(f"[retriever] Chroma 已加载: {CHROMA_DIR}")
    except Exception as e:
        print(f"[retriever] Chroma 加载失败（降级为图检索）: {e}")
        _chroma = _col_main = _col_style = None
else:
    print(f"[retriever] Chroma 目录不存在，使用图检索模式: {CHROMA_DIR}")

_neo4j = GraphDatabase.driver(
    _cfg["NEO4J_URI"],
    auth=(_cfg.get("NEO4J_USERNAME", "neo4j"), _cfg["NEO4J_PASSWORD"]),
)
_db = _cfg.get("NEO4J_DATABASE", "neo4j")


# ─────────────────────────── 嵌入 ─────────────────────────────
def _embed(text: str) -> list[float]:
    resp = _oai.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


# ─────────────────────────── 向量检索 ─────────────────────────
def _vec_retrieve(query: str, intent: str) -> list[dict]:
    """向量检索。Chroma 不可用时返回空列表（降级为纯图检索）。"""
    if _col_main is None:
        return []
    try:
        emb = _embed(query)
    except Exception as e:
        print(f"[retriever] embedding failed for vector retrieval: {e}")
        return []
    blocks = []

    try:
        if intent == "recommend":
            # 推荐优先走 style_seed，再补 main
            if _col_style:
                res = _col_style.query(query_embeddings=[emb], n_results=TOP_K_VEC)
                for doc, meta, dist in zip(
                    res["documents"][0], res["metadatas"][0], res["distances"][0]
                ):
                    blocks.append({
                        "source":  "vector",
                        "title":   meta.get("title", ""),
                        "section": meta.get("section", ""),
                        "text":    doc,
                        "score":   round(1 - dist, 4),
                        "meta":    meta,
                    })
            # 补充 main 的 summary/overview
            res2 = _col_main.query(
                query_embeddings=[emb],
                n_results=TOP_K_VEC,
                where={"section": {"$in": ["summary", "overview", "style_profile"]}},
            )
            for doc, meta, dist in zip(
                res2["documents"][0], res2["metadatas"][0], res2["distances"][0]
            ):
                blocks.append({
                    "source":  "vector",
                    "title":   meta.get("title", ""),
                    "section": meta.get("section", ""),
                    "text":    doc,
                    "score":   round(1 - dist, 4),
                    "meta":    meta,
                })
        else:
            # factual / relation：直接查 main，偏向 summary+overview
            for section_filter in [["summary", "overview", "tags", "characters"], None]:
                kwargs = dict(query_embeddings=[emb], n_results=TOP_K_VEC)
                if section_filter:
                    kwargs["where"] = {"section": {"$in": section_filter}}
                res = _col_main.query(**kwargs)
                for doc, meta, dist in zip(
                    res["documents"][0], res["metadatas"][0], res["distances"][0]
                ):
                    blocks.append({
                        "source":  "vector",
                        "title":   meta.get("title", ""),
                        "section": meta.get("section", ""),
                        "text":    doc,
                        "score":   round(1 - dist, 4),
                        "meta":    meta,
                    })
                if blocks:
                    break
    except Exception as e:
        print(f"[retriever] vector retrieval fallback: {e}")
        return []

    # 去重（同 title+section）
    seen = set()
    unique = []
    for b in blocks:
        key = (b["title"], b["section"])
        if key not in seen:
            seen.add(key)
            unique.append(b)

    # 过滤低相关性结果（负分或低于阈值的条目不应进入 prompt）
    unique = [b for b in unique if b.get("score") is None or b["score"] >= MIN_VEC_SCORE]

    return unique[:TOP_K_VEC + 4]


# ─────────────────────────── 图检索 ───────────────────────────

def _extract_anime_title(query: str) -> str | None:
    """从 query 里提取番名（简单启发式：去掉动词/功能词后的最长连续 CJK 串）"""
    # 去掉常见功能词
    strip_words = [
        "推荐", "类似", "同系列", "相关", "有哪些", "告诉我", "介绍",
        "的番", "的动漫", "的动画", "是什么", "讲什么", "怎么样", "几集",
        "首播", "时间", "声优", "配过", "系列", "前传", "续集", "衍生",
    ]
    q = query
    for w in strip_words:
        q = q.replace(w, " ")

    # 取最长的 CJK/英文词组（≥2字符），去掉单字连词开头
    CONNECTIVES = set("和与跟或及比")
    candidates = re.findall(r"[\u4e00-\u9fff\w]{2,}", q)
    if not candidates:
        return None
    # 去掉首字是连词的候选，并修剪
    cleaned = []
    for c in candidates:
        while c and c[0] in CONNECTIVES:
            c = c[1:]
        if len(c) >= 2:
            cleaned.append(c)
    if not cleaned:
        return None
    cleaned.sort(key=len, reverse=True)
    return cleaned[0]


def _extract_va_name(query: str) -> str | None:
    """
    提取声优名。
    数据库里声优名是日文（花澤香菜），用户可能输入简体（花泽香菜）或日文。
    策略：先精确匹配，再用 CONTAINS 模糊搜。
    """
    # 简单策略：取「声优/cv/配音」附近的名字
    patterns = [
        r"([\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,8})\s*(声优|配音|CV)",
        r"(声优|配音|CV)\s*([\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,8})",
        # 「花澤香菜配过」
        r"([\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{3,8})(配过|出演|配音)",
    ]
    for pat in patterns:
        m = re.search(pat, query)
        if m:
            groups = [g for g in m.groups() if g and g not in ("声优", "配音", "CV", "配过", "出演")]
            if groups:
                return groups[0]
    return None


def _graph_same_va(va_name: str) -> list[dict]:
    """查该声优配过的番"""
    with _neo4j.session(database=_db) as s:
        rows = s.run(
            "MATCH (v:VoiceActor) WHERE v.name = $name OR v.name CONTAINS $name "
            "WITH v LIMIT 1 "
            "MATCH (v)<-[:VOICED_BY]-(c:Character)<-[:HAS_CHARACTER]-(a:Anime) "
            "WHERE a.score IS NOT NULL AND a.id IS NOT NULL "
            "RETURN DISTINCT coalesce(a.name_cn, a.name) AS title, a.score AS score, "
            "       a.summary AS summary, c.name AS char, v.name AS va "
            "ORDER BY a.score DESC LIMIT $k",
            name=va_name, k=TOP_K_GRAPH,
        ).data()
    return [
        {
            "source":  "graph",
            "title":   r["title"] or "",
            "section": "voice_actor",
            "text":    f"声优 {r['va']} 在《{r['title']}》中配音角色 {r['char']}。\n简介：{r['summary'] or ''}",
            "score":   r["score"],
            "meta":    {"voice_actor": r["va"], "character": r["char"]},
        }
        for r in rows if r["title"]
    ]


def _graph_same_series(anime_title: str) -> list[dict]:
    """查同系列作品"""
    with _neo4j.session(database=_db) as s:
        rows = s.run(
            "MATCH (a:Anime) "
            "WHERE a.id IS NOT NULL "
            "  AND (a.name CONTAINS $title OR a.name_cn CONTAINS $title) "
            "WITH a ORDER BY coalesce(a.score, 0) DESC LIMIT 1 "
            "MATCH (a)-[r:RELATED_TO]-(b:Anime) "
            "WHERE coalesce(r.same_series, 0) = 1 "
            "RETURN DISTINCT coalesce(b.name_cn, b.name) AS title, b.score AS score, "
            "       b.summary AS summary, r.relation_type AS rel "
            "ORDER BY coalesce(b.score, 0) DESC LIMIT $k",
            title=anime_title, k=TOP_K_GRAPH,
        ).data()
    return [
        {
            "source":  "graph",
            "title":   r["title"] or "",
            "section": "related_works",
            "text":    f"[{r['rel']}]《{r['title']}》(score={r['score']})\n简介：{r['summary'] or ''}",
            "score":   r["score"],
            "meta":    {"relation_type": r["rel"]},
        }
        for r in rows if r["title"]
    ]


def _lookup_source_anime(anime_title: str) -> dict | None:
    """根据番名查源番，优先返回有 summary 的最佳匹配。"""
    with _neo4j.session(database=_db) as s:
        rows = s.run(
            "MATCH (src:Anime) "
            "WHERE src.id IS NOT NULL "
            "  AND (src.name CONTAINS $title OR src.name_cn CONTAINS $title) "
            "RETURN src.id AS id, "
            "       coalesce(src.name_cn, src.name) AS title, "
            "       coalesce(src.summary, '') AS summary, "
            "       coalesce(src.score, 0) AS score "
            "ORDER BY CASE WHEN trim(coalesce(src.summary, '')) <> '' THEN 0 ELSE 1 END ASC, "
            "         coalesce(src.score, 0) DESC "
            "LIMIT 1",
            title=anime_title,
        ).data()
    return rows[0] if rows else None


def _vec_similar_by_summary(anime_title: str) -> list[dict]:
    """
    用源番 summary 的 embedding 查 Chroma summary section，
    替代基于共享标签的相似推荐。

    fallback:
      - 找不到源番 / 源番没有 summary
      - Chroma 不可用
      - Chroma 中没有可用的 summary chunk
    这些情况返回 []，由 retrieve() 后续的 _vec_retrieve(query, intent) 继续兜底。
    """
    if _col_main is None:
        return []

    src = _lookup_source_anime(anime_title)
    if not src:
        return []

    src_summary = (src.get("summary") or "").strip()
    src_id = src.get("id")
    src_title = src.get("title") or anime_title
    if not src_summary:
        return []

    try:
        emb = _embed(src_summary)
        # 多取一些结果，方便过滤掉源番自身后还能保留足够候选。
        res = _col_main.query(
            query_embeddings=[emb],
            n_results=max(TOP_K_GRAPH * 3, 12),
            where={"section": "summary"},
        )
    except Exception as e:
        print(f"[retriever] summary similarity fallback for '{src_title}': {e}")
        return []

    blocks = []
    seen_entity_ids = set()

    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, dists):
        if not meta:
            continue

        entity_id = str(meta.get("entity_id", "")).strip()
        if src_id is not None and entity_id == str(src_id):
            continue
        if entity_id in seen_entity_ids:
            continue
        seen_entity_ids.add(entity_id)

        title = meta.get("title_cn") or meta.get("title") or ""
        if not title:
            continue

        score = round(1 - dist, 4) if dist is not None else None
        blocks.append({
            "source": "vector",
            "title": title,
            "section": "summary_similar",
            "text": f"《{title}》\n简介：{doc}",
            "score": score,
            "meta": {
                "entity_id": entity_id,
                "based_on": src_title,
                "match_section": "summary",
            },
        })

        if len(blocks) >= TOP_K_GRAPH:
            break

    return blocks


# ─────────────────────────── 主入口 ───────────────────────────
def retrieve(query: str) -> list[dict]:
    """
    混合检索：向量 + 图，按 intent 组合。
    返回去重、排序后的 block 列表（最多 TOP_K_VEC+TOP_K_GRAPH 条）。
    """
    cls = classify(query)
    intent  = cls["intent"]
    rel_type = cls["hints"]["want_relation_type"]

    blocks = []

    # ── 图检索部分 ──
    if intent == "relation":
        if rel_type == "same_va":
            va = _extract_va_name(query)
            if va:
                blocks += _graph_same_va(va)
        elif rel_type == "same_series":
            title = _extract_anime_title(query)
            if title:
                blocks += _graph_same_series(title)
        else:
            # 通用关系：先按系列，再补向量
            title = _extract_anime_title(query)
            if title:
                blocks += _graph_same_series(title)

    elif intent == "recommend":
        # 优先使用源番 summary 的向量相似推荐；没有 summary 时由后面的
        # _vec_retrieve(query, intent) 继续兜底。
        title = _extract_anime_title(query)
        if title:
            blocks += _vec_similar_by_summary(title)

    # ── 向量检索（所有 intent 都补充）──
    blocks += _vec_retrieve(query, intent)

    # ── 全局去重（title+section）──
    seen = set()
    unique = []
    for b in blocks:
        key = (b["title"][:30], b["section"])
        if key not in seen:
            seen.add(key)
            unique.append(b)

    return unique[:TOP_K_VEC + TOP_K_GRAPH]


# ─────────────────────────── CLI 测试 ─────────────────────────
if __name__ == "__main__":
    import sys

    queries = [
        "推荐和进击的巨人类似的番",
        "花澤香菜配过哪些角色？",
        "Code Geass 的系列作品有哪些",
        "我想看治愈系的番",
        "鬼灭之刃讲什么故事",
    ]
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    items = [q] if q else queries

    for query in items:
        print(f"\n{'─'*60}")
        print(f"Q: {query}")
        cls = classify(query)
        print(f"Intent: {cls['intent']}  rel_type: {cls['hints']['want_relation_type']}")
        blocks = retrieve(query)
        print(f"共 {len(blocks)} 个 block")
        for i, b in enumerate(blocks[:5], 1):
            src_tag = f"[{b['source']}/{b['section']}]"
            print(f"  {i}. {src_tag} 《{b['title']}》 score={b['score']}")
            print(f"     {b['text'][:80].strip()}…")
