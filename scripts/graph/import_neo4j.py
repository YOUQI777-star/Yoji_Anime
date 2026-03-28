"""
Neo4j Aura 全量数据导入脚本
从 data/processed/ 的四张表构建图数据库

节点：Anime · Tag · Character · VoiceActor
关系：HAS_TAG · HAS_CHARACTER · VOICED_BY · RELATED_TO

运行方式：
    python scripts/graph/import_neo4j.py
"""

import math
import re
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase

# ─────────────────────────── 配置 ────────────────────────────
ROOT     = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
DATA_DIR = ROOT / "data" / "processed"

BATCH = 500   # 每批写入条数


# ─────────────────────────── 读取连接信息 ─────────────────────
def load_neo4j_config(path: Path) -> dict:
    cfg = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg

cfg = load_neo4j_config(KEY_FILE)
URI      = cfg["NEO4J_URI"]
USER     = cfg.get("NEO4J_USERNAME", "neo4j")
PASSWORD = cfg["NEO4J_PASSWORD"]
DATABASE = cfg.get("NEO4J_DATABASE", "neo4j")

print(f"连接 Neo4j Aura: {URI}")
print(f"数据库: {DATABASE}  用户: {USER}")


# ─────────────────────────── 工具函数 ─────────────────────────
def clean(val):
    """把 NaN / 'nan' / 空字符串统一处理为 None"""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    return None if s.lower() in ("nan", "", "none") else s


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i: i + n]


def run_batch(session, query, records):
    session.run(query, records=records)


# ─────────────────────────── 读数据 ───────────────────────────
print("\n读取 processed 数据...")
anime_df   = pd.read_csv(DATA_DIR / "anime_master.csv")
tag_df     = pd.read_csv(DATA_DIR / "anime_tag_clean.csv")
char_df    = pd.read_csv(DATA_DIR / "anime_character_clean.csv")
rel_df     = pd.read_csv(DATA_DIR / "anime_relations_clean.csv")

print(f"  anime_master:    {len(anime_df):,}")
print(f"  tag_clean:       {len(tag_df):,}")
print(f"  character_clean: {len(char_df):,}")
print(f"  relations_clean: {len(rel_df):,}")


# ─────────────────────────── 连接 & 导入 ──────────────────────
driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

with driver.session(database=DATABASE) as s:

    # ── 0. 清空旧数据（可选，重跑时用 MERGE 去重所以其实不必要）──
    # s.run("MATCH (n) DETACH DELETE n")

    # ── 1. 约束 & 索引 ──────────────────────────────────────────
    print("\n[1/5] 建立约束和索引...")
    constraints = [
        "CREATE CONSTRAINT anime_id IF NOT EXISTS FOR (a:Anime)      REQUIRE a.anime_id IS UNIQUE",
        "CREATE CONSTRAINT tag_name  IF NOT EXISTS FOR (t:Tag)        REQUIRE t.name IS UNIQUE",
        "CREATE CONSTRAINT char_key  IF NOT EXISTS FOR (c:Character)  REQUIRE c.char_key IS UNIQUE",
        "CREATE CONSTRAINT va_name   IF NOT EXISTS FOR (v:VoiceActor) REQUIRE v.name IS UNIQUE",
    ]
    for c in constraints:
        try:
            s.run(c)
        except Exception as e:
            print(f"  约束已存在或跳过: {e}")

    # ── 2. Anime 节点 ────────────────────────────────────────────
    print("\n[2/5] 导入 Anime 节点...")
    anime_records = []
    for _, row in anime_df.iterrows():
        anime_records.append({
            "anime_id": int(row["anime_id"]),
            "name_ja":  clean(row.get("name_ja")),
            "name_cn":  clean(row.get("name_cn")),
            "title":    clean(row.get("title_display")) or clean(row.get("name_cn")) or clean(row.get("name_ja")),
            "date":     clean(row.get("date")),
            "country":  clean(row.get("country")),
            "platform": clean(row.get("platform")),
            "score":    float(row["score"]) if pd.notna(row.get("score")) else None,
            "rank":     int(row["rank"])    if pd.notna(row.get("rank"))  else None,
            "episodes": float(row["episodes"]) if pd.notna(row.get("episodes")) else None,
            "studio":   clean(row.get("studio")),
            "director": clean(row.get("director")),
            "summary":  clean(row.get("summary")),
        })

    cypher_anime = """
    UNWIND $records AS r
    MERGE (a:Anime {anime_id: r.anime_id})
    SET a.name_ja  = r.name_ja,
        a.name_cn  = r.name_cn,
        a.title    = r.title,
        a.date     = r.date,
        a.country  = r.country,
        a.platform = r.platform,
        a.score    = r.score,
        a.rank     = r.rank,
        a.episodes = r.episodes,
        a.studio   = r.studio,
        a.director = r.director,
        a.summary  = r.summary
    """
    for batch in batches(anime_records, BATCH):
        run_batch(s, cypher_anime, batch)
    print(f"  完成: {len(anime_records):,} 部番")

    # ── 3. Tag 节点 + HAS_TAG 关系 ──────────────────────────────
    print("\n[3/5] 导入 Tag 节点 & HAS_TAG 关系...")
    tag_records = []
    for _, row in tag_df.iterrows():
        tag = clean(row.get("tag"))
        if tag:
            tag_records.append({
                "anime_id": int(row["anime_id"]),
                "tag":      tag,
            })

    cypher_tag = """
    UNWIND $records AS r
    MERGE (t:Tag {name: r.tag})
    WITH t, r
    MATCH (a:Anime {anime_id: r.anime_id})
    MERGE (a)-[:HAS_TAG]->(t)
    """
    for batch in batches(tag_records, BATCH):
        run_batch(s, cypher_tag, batch)
    print(f"  完成: {len(tag_records):,} 条标签关系")

    # ── 4. Character 节点 + VoiceActor + 关系 ────────────────────
    print("\n[4/5] 导入 Character & VoiceActor 节点...")

    # char_key = "{anime_id}__{character_ja}" 保证唯一
    char_records = []
    seen_chars = set()
    va_records = []

    for _, row in char_df.iterrows():
        anime_id    = int(row["anime_id"])
        char_ja     = clean(row.get("character"))
        char_cn     = clean(row.get("name_cn"))
        cv          = clean(row.get("cv"))
        relation    = clean(row.get("relation"))

        if not char_ja:
            continue

        char_key = f"{anime_id}__{char_ja}"

        # Character 节点（去重）
        if char_key not in seen_chars:
            seen_chars.add(char_key)
            char_records.append({
                "char_key": char_key,
                "anime_id": anime_id,
                "name_ja":  char_ja,
                "name_cn":  char_cn,
                "relation": relation,
            })

        # VoiceActor + VOICED_BY
        if cv:
            va_records.append({
                "char_key": char_key,
                "va_name":  cv,
            })

    # 建 Character 节点 + HAS_CHARACTER 关系
    cypher_char = """
    UNWIND $records AS r
    MERGE (c:Character {char_key: r.char_key})
    SET c.name_ja  = r.name_ja,
        c.name_cn  = r.name_cn,
        c.relation = r.relation
    WITH c, r
    MATCH (a:Anime {anime_id: r.anime_id})
    MERGE (a)-[:HAS_CHARACTER]->(c)
    """
    for batch in batches(char_records, BATCH):
        run_batch(s, cypher_char, batch)
    print(f"  Character 节点: {len(char_records):,}")

    # 建 VoiceActor 节点 + VOICED_BY 关系
    cypher_va = """
    UNWIND $records AS r
    MERGE (v:VoiceActor {name: r.va_name})
    WITH v, r
    MATCH (c:Character {char_key: r.char_key})
    MERGE (c)-[:VOICED_BY]->(v)
    """
    for batch in batches(va_records, BATCH):
        run_batch(s, cypher_va, batch)
    print(f"  VoiceActor 节点 + VOICED_BY: {len(va_records):,} 条")

    # ── 5. RELATED_TO 关系 ──────────────────────────────────────
    print("\n[5/5] 导入 RELATED_TO 关系...")
    rel_records = []
    for _, row in rel_df.iterrows():
        src = clean(row.get("source_id"))
        tgt = clean(row.get("target_id"))
        if not src or not tgt:
            continue
        rel_records.append({
            "source_id":   int(src),
            "target_id":   int(tgt),
            "target_name": clean(row.get("target_name_cn")) or clean(row.get("target_name")),
            "rel_type":    clean(row.get("relation_type")),
            "same_series": int(row["same_series"]) if pd.notna(row.get("same_series")) else 0,
            "group":       clean(row.get("group")),
        })

    cypher_rel = """
    UNWIND $records AS r
    MATCH (src:Anime {anime_id: r.source_id})
    MATCH (tgt:Anime {anime_id: r.target_id})
    MERGE (src)-[rel:RELATED_TO {rel_type: r.rel_type}]->(tgt)
    SET rel.same_series  = r.same_series,
        rel.group        = r.group,
        rel.target_name  = r.target_name
    """
    # RELATED_TO 只处理 target 在库内的（source 已保证在库内）
    for batch in batches(rel_records, BATCH):
        run_batch(s, cypher_rel, batch)
    print(f"  完成: {len(rel_records):,} 条关联关系")

driver.close()
print("\n✅ 全部导入完成！")
