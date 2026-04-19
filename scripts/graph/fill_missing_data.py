"""
fill_missing_data.py
从 Bangumi Archive 补全 Neo4j 中无 summary 的 Anime 节点。

只更新，不新建节点。只 SET 当前为空的字段，有值的一律不动。
更新字段：summary, score, rank, name_cn

用法：
    # 先 dry run 看会改什么（不写数据库）
    python scripts/graph/fill_missing_data.py --dry-run

    # 确认没问题再实际写入
    python scripts/graph/fill_missing_data.py

    # 写完之后检查有没有重复节点
    python scripts/graph/fill_missing_data.py --dedup-check
"""

import argparse
import json
import zipfile
from pathlib import Path

from neo4j import GraphDatabase

# ─────────────────────────── 配置 ────────────────────────────
ROOT     = Path(__file__).parent.parent.parent
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
ARCHIVE  = Path("/tmp/bangumi_archive.zip")

BATCH = 200   # 每批写入条数
ANIME_TYPE = 2  # Bangumi type=2 是 anime


# ─────────────────────────── 连接 ─────────────────────────────
def load_neo4j_config(path: Path) -> dict:
    cfg = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def get_driver():
    cfg = load_neo4j_config(KEY_FILE)
    return GraphDatabase.driver(
        cfg["NEO4J_URI"],
        auth=(cfg.get("NEO4J_USERNAME", "neo4j"), cfg["NEO4J_PASSWORD"]),
    ), cfg.get("NEO4J_DATABASE", "neo4j")


# ─────────────────────────── 工具 ─────────────────────────────
def clean(val):
    """NaN / None / 空字符串 → None"""
    if val is None:
        return None
    s = str(val).strip()
    return None if s.lower() in ("nan", "", "none") else s


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ─────────────────────────── 步骤一：拿缺失 id ───────────────
def get_missing_ids(driver, db) -> set[int]:
    """从 Neo4j 拿所有 summary 为空的 Anime id"""
    with driver.session(database=db) as s:
        rows = s.run("""
            MATCH (a:Anime)
            WHERE a.id IS NOT NULL
              AND (a.summary IS NULL OR trim(a.summary) = "")
            RETURN a.id AS id
        """).data()
    ids = {r["id"] for r in rows}
    print(f"Neo4j 中无 summary 的节点: {len(ids)} 个")
    return ids


# ─────────────────────────── 步骤二：扫 Archive ──────────────
def scan_archive(missing_ids: set[int]) -> list[dict]:
    """
    流式读取 subject.jsonlines，
    只保留 type=2 (anime)、nsfw=False、id 在 missing_ids 里的条目。
    """
    print(f"\n扫描 Archive: {ARCHIVE}")
    if not ARCHIVE.exists():
        raise FileNotFoundError(f"Archive 不存在: {ARCHIVE}")

    found = []
    scanned = 0

    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        with zf.open("subject.jsonlines") as f:
            for raw in f:
                scanned += 1
                if scanned % 100_000 == 0:
                    print(f"  已扫描 {scanned:,} 条，匹配 {len(found)} 条...")

                obj = json.loads(raw)

                # 过滤条件
                if obj.get("type") != ANIME_TYPE:
                    continue
                if obj.get("nsfw", True):
                    continue
                if obj["id"] not in missing_ids:
                    continue

                summary = clean(obj.get("summary", ""))
                score   = obj.get("score")
                rank    = obj.get("rank")
                name_cn = clean(obj.get("name_cn", ""))

                # Archive 里 score=0/rank=0 表示无数据，视为 None
                if score == 0:
                    score = None
                if rank == 0:
                    rank = None

                found.append({
                    "id":      obj["id"],
                    "summary": summary,
                    "score":   score,
                    "rank":    rank,
                    "name_cn": name_cn,
                })

    print(f"扫描完成: 共 {scanned:,} 条，匹配到 {len(found)} 个目标 anime")
    return found


# ─────────────────────────── 步骤三：写入 Neo4j ──────────────
MERGE_QUERY = """
UNWIND $records AS rec
MATCH (a:Anime {id: rec.id})
SET a.summary  = CASE WHEN a.summary  IS NULL OR trim(a.summary)  = "" THEN rec.summary  ELSE a.summary  END,
    a.score    = CASE WHEN a.score    IS NULL                           THEN rec.score    ELSE a.score    END,
    a.rank     = CASE WHEN a.rank     IS NULL                           THEN rec.rank     ELSE a.rank     END,
    a.name_cn  = CASE WHEN a.name_cn  IS NULL OR trim(a.name_cn)  = "" THEN rec.name_cn  ELSE a.name_cn  END
"""


def write_to_neo4j(driver, db, records: list[dict], dry_run: bool):
    if dry_run:
        print(f"\n[DRY RUN] 会更新 {len(records)} 个节点，不写入数据库")
        print("样本（前10条）：")
        for r in records[:10]:
            print(f"  id={r['id']}  score={r['score']}  rank={r['rank']}"
                  f"  summary={'有(' + str(len(r['summary'])) + '字)' if r['summary'] else '无'}"
                  f"  name_cn={r['name_cn']}")
        return

    print(f"\n开始写入 {len(records)} 条记录，每批 {BATCH} 条...")
    written = 0
    with driver.session(database=db) as s:
        for batch in batches(records, BATCH):
            s.run(MERGE_QUERY, records=batch)
            written += len(batch)
            print(f"  已写入 {written}/{len(records)}", end="\r")
    print(f"\n写入完成：{written} 条")


# ─────────────────────────── 步骤四：去重检查 ────────────────
def dedup_check(driver, db):
    print("\n===== 去重检查 =====")
    with driver.session(database=db) as s:
        # 检查同 id 出现多次的情况
        rows = s.run("""
            MATCH (a:Anime)
            WHERE a.id IS NOT NULL
            WITH a.id AS id, count(*) AS cnt
            WHERE cnt > 1
            RETURN id, cnt
            ORDER BY cnt DESC
            LIMIT 20
        """).data()

        if rows:
            print(f"⚠️  发现 {len(rows)} 个重复 id：")
            for r in rows:
                print(f"  id={r['id']}  出现 {r['cnt']} 次")
        else:
            print("✅  无重复节点，数据库干净")

        # 顺便统计更新后的 summary 覆盖率
        row = s.run("""
            MATCH (a:Anime)
            RETURN
                count(a) AS total,
                count(CASE WHEN a.summary IS NOT NULL AND trim(a.summary) <> "" THEN 1 END) AS has_summary
        """).single()
        total = row["total"]
        has   = row["has_summary"]
        print(f"\n更新后 summary 覆盖率: {has}/{total} ({has*100//total}%)")


# ─────────────────────────── 主流程 ──────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",      action="store_true", help="只看会改什么，不写数据库")
    parser.add_argument("--dedup-check",  action="store_true", help="只做去重检查，不导入")
    args = parser.parse_args()

    driver, db = get_driver()
    print(f"已连接 Neo4j (database={db})\n")

    if args.dedup_check:
        dedup_check(driver, db)
        driver.close()
        return

    # 1. 拿缺失 id
    missing_ids = get_missing_ids(driver, db)
    if not missing_ids:
        print("所有节点都有 summary，无需更新")
        driver.close()
        return

    # 2. 扫 Archive
    records = scan_archive(missing_ids)
    if not records:
        print("Archive 中没有匹配到任何记录")
        driver.close()
        return

    # 3. 写入（或 dry run）
    write_to_neo4j(driver, db, records, dry_run=args.dry_run)

    # 4. 写完之后自动做去重检查
    if not args.dry_run:
        dedup_check(driver, db)

    driver.close()
    print("\n完成")


if __name__ == "__main__":
    main()
