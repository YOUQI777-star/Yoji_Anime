"""
Neo4j 图数据库验证脚本
运行各类 Cypher 查询，确认节点/关系数量和典型图遍历都正确。

运行方式：
    python scripts/graph/test_graph_queries.py
"""

from pathlib import Path
from neo4j import GraphDatabase

# ─────────────────────────── 配置 ────────────────────────────
ROOT     = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"


def load_neo4j_config(path: Path) -> dict:
    cfg = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


cfg      = load_neo4j_config(KEY_FILE)
URI      = cfg["NEO4J_URI"]
USER     = cfg.get("NEO4J_USERNAME", "neo4j")
PASSWORD = cfg["NEO4J_PASSWORD"]
DATABASE = cfg.get("NEO4J_DATABASE", "neo4j")

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

SEP = "─" * 60


def q(session, cypher, **params):
    return session.run(cypher, **params).data()


with driver.session(database=DATABASE) as s:

    # ── 1. 节点 & 关系计数 ───────────────────────────────────────
    print(f"\n{SEP}")
    print("【1】节点 & 关系总量")
    print(SEP)

    counts = [
        ("Anime",      "MATCH (n:Anime)      RETURN count(n) AS cnt"),
        ("Tag",        "MATCH (n:Tag)        RETURN count(n) AS cnt"),
        ("Character",  "MATCH (n:Character)  RETURN count(n) AS cnt"),
        ("VoiceActor", "MATCH (n:VoiceActor) RETURN count(n) AS cnt"),
        ("HAS_TAG",       "MATCH ()-[r:HAS_TAG]->()       RETURN count(r) AS cnt"),
        ("HAS_CHARACTER", "MATCH ()-[r:HAS_CHARACTER]->() RETURN count(r) AS cnt"),
        ("VOICED_BY",     "MATCH ()-[r:VOICED_BY]->()     RETURN count(r) AS cnt"),
        ("RELATED_TO",    "MATCH ()-[r:RELATED_TO]->()    RETURN count(r) AS cnt"),
    ]
    for label, cypher in counts:
        cnt = q(s, cypher)[0]["cnt"]
        print(f"  {label:<18} {cnt:>8,}")

    # ── 2. 高分番（score ≥ 9.0）────────────────────────────────
    print(f"\n{SEP}")
    print("【2】score ≥ 9.0 的番（前 10）")
    print(SEP)
    rows = q(s,
        "MATCH (a:Anime) WHERE a.score >= 9.0 "
        "RETURN a.title AS title, a.score AS score, a.studio AS studio "
        "ORDER BY a.score DESC LIMIT 10"
    )
    for r in rows:
        print(f"  {r['score']:.1f}  {r['title']}  [{r['studio']}]")

    # ── 3. 声优代表作（配音角色最多的声优 Top 10）──────────────
    print(f"\n{SEP}")
    print("【3】配音角色数最多的声优 Top 10")
    print(SEP)
    rows = q(s,
        "MATCH (v:VoiceActor)<-[:VOICED_BY]-(c:Character) "
        "RETURN v.name AS va, count(c) AS roles "
        "ORDER BY roles DESC LIMIT 10"
    )
    for r in rows:
        print(f"  {r['roles']:>4} 角色  {r['va']}")

    # ── 4. 某声优演过的动画（以花泽香菜为例）──────────────────
    print(f"\n{SEP}")
    print("【4】花泽香菜 配音的动画（前 10）")
    print(SEP)
    rows = q(s,
        "MATCH (v:VoiceActor {name: '花澤香菜'})<-[:VOICED_BY]-(c:Character)"
        "<-[:HAS_CHARACTER]-(a:Anime) "
        "RETURN DISTINCT a.title AS title, c.name_ja AS char, a.score AS score "
        "ORDER BY score DESC LIMIT 10"
    )
    if rows:
        for r in rows:
            print(f"  {r['title']}  饰 {r['char']}  score={r['score']}")
    else:
        print("  (未找到，检查声优名称格式)")

    # ── 5. 同系列作品（Code Geass 关联）───────────────────────
    print(f"\n{SEP}")
    print("【5】Code Geass 系列（RELATED_TO, same_series=1）")
    print(SEP)
    rows = q(s,
        "MATCH (a:Anime)-[r:RELATED_TO]-(b:Anime) "
        "WHERE (a.name_ja CONTAINS 'コードギアス' OR a.name_cn CONTAINS 'Code Geass' "
        "       OR a.title CONTAINS 'Code Geass') "
        "  AND r.same_series = 1 "
        "RETURN DISTINCT b.title AS title, b.score AS score, r.rel_type AS rel "
        "ORDER BY b.score DESC LIMIT 10"
    )
    if rows:
        for r in rows:
            print(f"  [{r['rel']}] {r['title']}  score={r['score']}")
    else:
        # fallback: show by anime_id
        rows2 = q(s,
            "MATCH (a:Anime {anime_id: 8})-[r:RELATED_TO]-(b:Anime) "
            "RETURN b.title AS title, b.score AS score, r.rel_type AS rel "
            "ORDER BY b.score DESC LIMIT 10"
        )
        for r in rows2:
            print(f"  [{r['rel']}] {r['title']}  score={r['score']}")

    # ── 6. 京阿尼高分番 ─────────────────────────────────────────
    print(f"\n{SEP}")
    print("【6】京都动画 出品，score ≥ 8.5（前 10）")
    print(SEP)
    rows = q(s,
        "MATCH (a:Anime) "
        "WHERE (a.studio CONTAINS '京都') AND a.score >= 8.5 "
        "RETURN a.title AS title, a.score AS score, a.date AS date "
        "ORDER BY a.score DESC LIMIT 10"
    )
    for r in rows:
        print(f"  {r['score']:.1f}  {r['title']}  ({r['date']})")

    # ── 7. 某标签下的高分番（以「战斗」为例）──────────────────
    print(f"\n{SEP}")
    print("【7】含「战斗」标签，score ≥ 8.5（前 10）")
    print(SEP)
    rows = q(s,
        "MATCH (a:Anime)-[:HAS_TAG]->(t:Tag) "
        "WHERE t.name CONTAINS '战斗' AND a.score >= 8.5 "
        "RETURN a.title AS title, a.score AS score, t.name AS tag "
        "ORDER BY a.score DESC LIMIT 10"
    )
    for r in rows:
        print(f"  {r['score']:.1f}  {r['title']}  [{r['tag']}]")

    # ── 8. 两部动画共有的标签数（相似度探测）──────────────────
    print(f"\n{SEP}")
    print("【8】与「进击的巨人」共享标签最多的动画 Top 5")
    print(SEP)
    rows = q(s,
        "MATCH (src:Anime {anime_id: 55770})-[:HAS_TAG]->(t:Tag)"
        "<-[:HAS_TAG]-(other:Anime) "
        "WHERE other.anime_id <> 55770 "
        "RETURN other.title AS title, other.score AS score, count(t) AS shared "
        "ORDER BY shared DESC, score DESC LIMIT 5"
    )
    for r in rows:
        print(f"  共 {r['shared']} 个标签  {r['title']}  score={r['score']}")

print(f"\n{SEP}")
print("✅ 验证完成")
print(SEP)

driver.close()
