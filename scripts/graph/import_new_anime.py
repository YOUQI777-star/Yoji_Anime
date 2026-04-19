"""
import_new_anime.py
从 Bangumi Archive 向 Neo4j 导入高质量新 Anime 及其关联数据。

筛选条件（高质量）：
  - type=2 (anime)
  - nsfw=False
  - 0 < rank < 3000
  - score 不为空且不为 0
  - id 不在现有 Neo4j 数据库中

导入内容：
  节点：Anime · Character · VoiceActor · Tag · Studio · Country
  关系：HAS_TAG · HAS_CHARACTER · VOICED_BY · PRODUCED_BY · ORIGIN_COUNTRY

用法：
  python scripts/graph/import_new_anime.py --dry-run      # 预览，不写入
  python scripts/graph/import_new_anime.py                # 实际导入
  python scripts/graph/import_new_anime.py --dedup-check  # 去重检查
"""

import argparse
import json
import re
import zipfile
from pathlib import Path

from neo4j import GraphDatabase

# ─── 配置 ─────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent.parent
KEY_FILE = ROOT / "Neo4j-2f775b9b-Created-2026-03-24.txt"
ARCHIVE  = Path("/tmp/bangumi_archive.zip")

BATCH      = 100
ANIME_TYPE = 2
RANK_MAX   = 3000

# ─── Tag 映射（Archive 用户标签 → 35 个目标 Tag 节点）────────────
TAG_MAP: dict[str, str] = {
    # 日本动画
    "日本": "日本动画", "日本动漫": "日本动画", "日本动画": "日本动画",
    # 中国动画
    "中国": "中国动画", "国产": "中国动画", "国漫": "中国动画",
    "中国动画": "中国动画", "华语": "中国动画",
    # 美国动画
    "美国": "美国动画", "欧美": "美国动画", "美国动画": "美国动画",
    # 剧场版
    "剧场版": "剧场版", "电影": "剧场版", "movie": "剧场版",
    # OVA
    "ova": "OVA", "oad": "OVA", "特别篇": "OVA",
    # 喜剧
    "喜剧": "喜剧", "搞笑": "喜剧", "コメディ": "喜剧",
    # 热血
    "热血": "热血", "燃": "热血", "少年": "热血",
    # 恋爱
    "恋爱": "恋爱", "恋愛": "恋爱", "爱情": "恋爱", "浪漫": "恋爱",
    # 奇幻
    "奇幻": "奇幻", "幻想": "奇幻", "魔法": "奇幻",
    "异世界": "奇幻", "isekai": "奇幻",
    # 科幻
    "科幻": "科幻", "sf": "科幻", "科学幻想": "科幻",
    "赛博朋克": "科幻", "超能力": "科幻",
    # 日常
    "日常": "日常", "萌系": "日常",
    # 治愈
    "治愈": "治愈", "疗愈": "治愈", "温馨": "治愈",
    # 悬疑
    "悬疑": "悬疑", "推理": "悬疑", "神秘": "悬疑", "犯罪": "悬疑",
    # 恐怖
    "恐怖": "恐怖", "惊悚": "恐怖",
    # 运动
    "运动": "运动", "体育": "运动", "スポーツ": "运动",
    # 音乐
    "音乐": "音乐", "音楽": "音乐", "偶像": "音乐",
    # 历史
    "历史": "历史", "战国": "历史", "古代": "历史",
    "武侠": "历史", "时代剧": "历史",
    # 战争
    "战争": "战争", "军事": "战争",
    # 冒险
    "冒险": "冒险", "探险": "冒险", "旅行": "冒险",
    # 校园
    "校园": "校园", "学园": "校园", "青春": "校园",
    # 职场
    "职场": "职场", "社会人": "职场",
    # 后宫
    "后宫": "后宫", "ハーレム": "后宫",
    # 百合
    "百合": "百合", "gl": "百合",
    # BL
    "bl": "BL", "耽美": "BL", "腐": "BL",
    # 竞技
    "竞技": "竞技", "游戏": "竞技", "电竞": "竞技",
    # 美食
    "美食": "美食", "料理": "美食", "グルメ": "美食",
    # 机甲
    "机甲": "机甲", "高达": "机甲", "ロボット": "机甲", "机器人": "机甲",
    # 超自然
    "超自然": "超自然", "灵异": "超自然", "鬼怪": "超自然",
    "妖怪": "超自然", "神话": "超自然",
    # 后末日
    "后末日": "后末日", "末世": "后末日", "废土": "后末日",
    "反乌托邦": "后末日",
    # 短片
    "短片": "短片", "短篇": "短片",
    # 儿童
    "儿童": "儿童", "幼儿": "儿童", "亲子": "儿童",
    # 原创
    "原创": "原创", "オリジナル": "原创",
    # 改编
    "漫改": "改编", "小说改编": "改编", "游戏改编": "改编", "轻改": "改编",
    # 催泪（新增第 35 个标签）
    "催泪": "催泪", "感人": "催泪", "泪点": "催泪", "虐心": "催泪", "悲剧": "催泪",
}

# ─── 国家标准化映射（infobox 原始值 → 现有 Country 节点名）───────
COUNTRY_NORM: dict[str, str] = {
    "日本": "Japan",      "japan": "Japan",
    "中国": "China",      "中国大陆": "China",    "china": "China",
    "美国": "U.S.A",      "usa": "U.S.A",         "u.s.a": "U.S.A",
    "韩国": "Korea",      "한국": "Korea",         "korea": "Korea",
    "法国": "France",     "france": "France",
    "英国": "U.K",        "uk": "U.K",             "u.k": "U.K",
    "德国": "Germany",    "germany": "Germany",
    "加拿大": "Canada",   "canada": "Canada",
    "澳大利亚": "Australia", "australia": "Australia",
    "西班牙": "Spain",    "spain": "Spain",
    "意大利": "Italy",    "italy": "Italy",
    "俄罗斯": "Russia",   "russia": "Russia",
}

# infobox 字段 key（按优先级顺序）
COUNTRY_KEYS = ["国家", "地区"]
STUDIO_KEYS  = ["动画制作", "制作公司", "アニメーション制作", "制作"]
DATE_KEYS    = ["放送开始", "上映年度", "发行日期", "首播时间", "开播日期"]
EP_KEYS      = ["话数", "集数", "话数（映画）"]


# ─── 工具函数 ──────────────────────────────────────────────────────
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


def clean(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return None if s.lower() in ("nan", "", "none") else s


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i: i + n]


def parse_infobox(infobox_str: str) -> dict[str, str]:
    """从 mediawiki 格式的 infobox 中提取简单 key=value 对。
    跳过以 { 开头的复杂值（列表/嵌套）。"""
    result: dict[str, str] = {}
    if not infobox_str:
        return result
    for line in infobox_str.splitlines():
        line = line.strip()
        if line.startswith("|") and "=" in line:
            key, _, val = line[1:].partition("=")
            key = key.strip()
            val = val.strip()
            if val and not val.startswith("{"):
                result[key] = val
    return result


def extract_cn_name(infobox_str: str) -> str | None:
    """从 infobox 的 |简体中文名= 提取中文名"""
    box = parse_infobox(infobox_str)
    return clean(box.get("简体中文名"))


def detect_country_from_context(name: str, infobox_str: str = "") -> str | None:
    """根据原名 + infobox 文本的字符集推断国家。
    先检测名称，纯汉字时再扫描 infobox（可能含片假名台/公司名）。"""
    text = name or ""

    def _has(s, lo, hi):
        return any(lo <= c <= hi for c in s)

    def classify(s):
        has_hiragana = _has(s, '\u3040', '\u309f')
        has_katakana = _has(s, '\u30a0', '\u30ff')
        has_hangul   = _has(s, '\uac00', '\ud7a3')
        has_cjk      = _has(s, '\u4e00', '\u9fff')
        has_latin    = any(c.isascii() and c.isalpha() for c in s)
        if has_hiragana or has_katakana:
            return "Japan"
        if has_hangul:
            return "Korea"
        if has_cjk and not has_latin:
            return "CJK"   # 暂定，需要进一步判断
        if has_latin:
            return "Latin"
        return None

    result = classify(text)

    # 纯汉字时，用 infobox 文本再检测一次（常含片假名台名/公司名）
    if result == "CJK" and infobox_str:
        result2 = classify(infobox_str)
        if result2 == "Japan":
            return "Japan"
        if result2 == "Korea":
            return "Korea"
        # infobox 也是纯 CJK / Latin → 大概率日本（Bangumi 主体是日本动画）
        return "Japan"

    if result == "CJK":
        return "Japan"      # 没有 infobox 时，纯汉字默认 Japan
    if result == "Latin":
        return "U.S.A"
    return result           # "Japan" / "Korea" / None


def normalize_country(raw: str | None) -> str | None:
    if not raw:
        return None
    return COUNTRY_NORM.get(raw.strip()) or COUNTRY_NORM.get(raw.strip().lower())


# ─── 步骤一：获取现有 Neo4j anime ID 集合 ─────────────────────────
def get_existing_ids(driver, db) -> set[int]:
    with driver.session(database=db) as s:
        rows = s.run("MATCH (a:Anime) WHERE a.id IS NOT NULL RETURN a.id AS id").data()
    ids = {r["id"] for r in rows}
    print(f"Neo4j 现有 Anime: {len(ids):,} 个")
    return ids


# ─── 步骤二：扫描 subject.jsonlines ───────────────────────────────
def scan_subjects(existing_ids: set[int]) -> tuple[list[dict], set[int]]:
    """返回 (qualifying_anime_list, qualifying_id_set)"""
    print(f"\n扫描 subject.jsonlines（这个文件很大，需要一点时间）...")
    found: list[dict] = []
    scanned = 0

    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        with zf.open("subject.jsonlines") as f:
            for raw in f:
                scanned += 1
                if scanned % 200_000 == 0:
                    print(f"  已扫描 {scanned:,} 条，匹配 {len(found)} 条...")

                obj = json.loads(raw)

                # 基础过滤
                if obj.get("type") != ANIME_TYPE:
                    continue
                if obj.get("nsfw", True):
                    continue

                rank  = obj.get("rank", 0)
                score = obj.get("score", 0)
                sid   = obj["id"]

                if not (0 < rank < RANK_MAX):
                    continue
                if not score or score == 0:
                    continue
                if sid in existing_ids:
                    continue

                # 解析 infobox
                box = parse_infobox(obj.get("infobox", ""))

                # 国家：infobox 优先，退路用字符集检测（同时扫描 infobox 文本）
                country_raw = next((box[k] for k in COUNTRY_KEYS if k in box), None)
                country = normalize_country(country_raw)
                if not country:
                    country = detect_country_from_context(
                        obj.get("name", ""), obj.get("infobox", "")
                    )

                # 制作公司
                studio = next((clean(box[k]) for k in STUDIO_KEYS if k in box), None)

                # 首播日期
                date = next((clean(box[k]) for k in DATE_KEYS if k in box), None)

                # 话数
                episodes = None
                ep_raw = next((box[k] for k in EP_KEYS if k in box), None)
                if ep_raw:
                    digits = re.sub(r"[^\d]", "", ep_raw)
                    if digits:
                        try:
                            episodes = int(digits)
                        except ValueError:
                            pass

                # 标签映射（大小写不敏感）
                tags: list[str] = []
                for t in obj.get("tags", []):
                    raw_name = t.get("name", "")
                    mapped = TAG_MAP.get(raw_name) or TAG_MAP.get(raw_name.lower())
                    if mapped:
                        tags.append(mapped)
                tags = list(set(tags))

                found.append({
                    "id":       sid,
                    "name":     clean(obj.get("name")),
                    "name_cn":  clean(obj.get("name_cn")),
                    "summary":  clean(obj.get("summary")),
                    "score":    float(score),
                    "rank":     int(rank),
                    "date":     date,
                    "episodes": episodes,
                    "studio":   studio,
                    "country":  country,
                    "tags":     tags,
                })

    qualifying_ids = {a["id"] for a in found}
    print(f"扫描完成: 共 {scanned:,} 条 → 符合条件的新 anime: {len(found)} 部")
    return found, qualifying_ids


# ─── 步骤三：扫描角色 / 声优文件 ──────────────────────────────────
def scan_characters(qualifying_ids: set[int]) -> tuple[
    dict[int, dict],      # char_map:   character_id → {id, name, name_cn}
    dict[int, list],      # subj_chars: subject_id   → [(character_id, ctype)]
    dict[tuple, int],     # va_map:     (char_id, subj_id) → person_id
    dict[int, dict],      # person_map: person_id → {name, name_cn}
]:
    # ── 3-1. subject-characters ──────────────────────────────────
    print("\n扫描 subject-characters.jsonlines...")
    subj_chars: dict[int, list] = {}
    needed_char_ids: set[int] = set()
    scanned = 0

    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        with zf.open("subject-characters.jsonlines") as f:
            for raw in f:
                scanned += 1
                obj = json.loads(raw)
                sid   = obj.get("subject_id")
                cid   = obj.get("character_id")
                ctype = obj.get("type", 3)

                if sid not in qualifying_ids:
                    continue
                if ctype not in (1, 2):     # 1=主角 2=配角，跳过客串
                    continue

                subj_chars.setdefault(sid, []).append((cid, ctype))
                needed_char_ids.add(cid)

    print(f"  {scanned:,} 条中，涉及 {len(needed_char_ids):,} 个角色")

    # ── 3-2. character.jsonlines ─────────────────────────────────
    print("扫描 character.jsonlines...")
    char_map: dict[int, dict] = {}
    scanned = 0

    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        with zf.open("character.jsonlines") as f:
            for raw in f:
                scanned += 1
                obj = json.loads(raw)
                cid = obj["id"]
                if cid not in needed_char_ids:
                    continue
                char_map[cid] = {
                    "name":    clean(obj.get("name")),
                    "name_cn": extract_cn_name(obj.get("infobox", "")),
                }

    print(f"  {scanned:,} 条中，找到 {len(char_map):,} 个目标角色")

    # ── 3-3. person-characters.jsonlines（声优映射）──────────────
    print("扫描 person-characters.jsonlines...")
    va_map: dict[tuple, int] = {}
    needed_person_ids: set[int] = set()
    scanned = 0

    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        with zf.open("person-characters.jsonlines") as f:
            for raw in f:
                scanned += 1
                obj = json.loads(raw)
                sid = obj.get("subject_id")
                cid = obj.get("character_id")
                pid = obj.get("person_id")

                if sid not in qualifying_ids:
                    continue
                if cid not in needed_char_ids:
                    continue

                key = (cid, sid)
                if key not in va_map:       # 同角色同作品取第一条
                    va_map[key] = pid
                    needed_person_ids.add(pid)

    print(f"  {scanned:,} 条中，找到 {len(va_map):,} 条配音记录，"
          f"涉及 {len(needed_person_ids):,} 位声优")

    # ── 3-4. person.jsonlines ─────────────────────────────────────
    print("扫描 person.jsonlines...")
    person_map: dict[int, dict] = {}
    scanned = 0

    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        with zf.open("person.jsonlines") as f:
            for raw in f:
                scanned += 1
                obj = json.loads(raw)
                pid = obj["id"]
                if pid not in needed_person_ids:
                    continue
                if "seiyu" not in obj.get("career", []):
                    continue                 # 只要声优，不要其他工作人员
                person_map[pid] = {
                    "name":    clean(obj.get("name")),
                    "name_cn": extract_cn_name(obj.get("infobox", "")),
                }

    print(f"  {scanned:,} 条中，找到 {len(person_map):,} 位目标声优")
    return char_map, subj_chars, va_map, person_map


# ─── 步骤四：写入 Neo4j ────────────────────────────────────────────

_Q_ANIME = """
UNWIND $records AS r
MERGE (a:Anime {id: r.id})
ON CREATE SET
    a.name     = r.name,
    a.name_cn  = r.name_cn,
    a.summary  = r.summary,
    a.score    = r.score,
    a.rank     = r.rank,
    a.date     = r.date,
    a.episodes = r.episodes,
    a.studio   = r.studio
"""

_Q_TAG = """
UNWIND $records AS r
MERGE (t:Tag {name: r.tag})
WITH t, r
MATCH (a:Anime {id: r.anime_id})
MERGE (a)-[:HAS_TAG]->(t)
"""

_Q_COUNTRY = """
UNWIND $records AS r
MERGE (c:Country {name: r.country})
WITH c, r
MATCH (a:Anime {id: r.anime_id})
MERGE (a)-[:ORIGIN_COUNTRY]->(c)
"""

_Q_STUDIO = """
UNWIND $records AS r
MERGE (s:Studio {name: r.studio})
WITH s, r
MATCH (a:Anime {id: r.anime_id})
MERGE (a)-[:PRODUCED_BY]->(s)
"""

_Q_CHAR = """
UNWIND $records AS r
MERGE (c:Character {id: r.char_id})
ON CREATE SET
    c.name    = r.name,
    c.name_cn = r.name_cn
WITH c, r
MATCH (a:Anime {id: r.anime_id})
MERGE (a)-[:HAS_CHARACTER]->(c)
"""

_Q_VA = """
UNWIND $records AS r
MERGE (v:VoiceActor {name: r.va_name})
WITH v, r
MATCH (c:Character {id: r.char_id})
MERGE (c)-[:VOICED_BY]->(v)
"""


def write_to_neo4j(
    driver, db,
    anime_list:  list[dict],
    char_map:    dict[int, dict],
    subj_chars:  dict[int, list],
    va_map:      dict[tuple, int],
    person_map:  dict[int, dict],
    dry_run:     bool,
):
    if dry_run:
        total_chars = sum(len(v) for v in subj_chars.values())
        print(f"\n[DRY RUN] 预计新增：")
        print(f"  Anime       : {len(anime_list):,} 部")
        print(f"  HAS_TAG     : {sum(len(a['tags']) for a in anime_list):,} 条")
        print(f"  ORIGIN_COUNTRY: {sum(1 for a in anime_list if a['country']):,} 条")
        print(f"  PRODUCED_BY : {sum(1 for a in anime_list if a['studio']):,} 条")
        print(f"  Character   : {total_chars:,} 条（角色节点 ≤ {len(char_map):,}）")
        print(f"  VoiceActor  : ≤ {len(person_map):,} 人")
        print(f"\n样本 Anime（前 5 条）：")
        for a in anime_list[:5]:
            print(f"  rank={a['rank']:4d}  score={a['score']:.2f}  "
                  f"name={a['name']}  country={a['country']}  studio={a['studio']}")
            print(f"           tags={a['tags']}")
        return

    with driver.session(database=db) as s:

        # 1. Anime 节点
        print(f"\n[1/6] 写入 {len(anime_list):,} 个 Anime 节点...")
        written = 0
        for batch in batches(anime_list, BATCH):
            s.run(_Q_ANIME, records=batch)
            written += len(batch)
            print(f"  {written}/{len(anime_list)}", end="\r")
        print()

        # 2. HAS_TAG
        tag_records = [
            {"anime_id": a["id"], "tag": tag}
            for a in anime_list for tag in a["tags"]
        ]
        print(f"[2/6] 写入 {len(tag_records):,} 条 HAS_TAG 关系...")
        for batch in batches(tag_records, BATCH):
            s.run(_Q_TAG, records=batch)
        print("  完成")

        # 3. ORIGIN_COUNTRY
        country_records = [
            {"anime_id": a["id"], "country": a["country"]}
            for a in anime_list if a["country"]
        ]
        print(f"[3/6] 写入 {len(country_records):,} 条 ORIGIN_COUNTRY 关系...")
        for batch in batches(country_records, BATCH):
            s.run(_Q_COUNTRY, records=batch)
        print("  完成")

        # 4. PRODUCED_BY
        studio_records = [
            {"anime_id": a["id"], "studio": a["studio"]}
            for a in anime_list if a["studio"]
        ]
        print(f"[4/6] 写入 {len(studio_records):,} 条 PRODUCED_BY 关系...")
        for batch in batches(studio_records, BATCH):
            s.run(_Q_STUDIO, records=batch)
        print("  完成")

        # 5. HAS_CHARACTER
        char_records: list[dict] = []
        seen_char_ids: set[str] = set()

        for sid, clist in subj_chars.items():
            for (cid, _ctype) in clist:
                if cid not in char_map:
                    continue
                char = char_map[cid]
                if not char["name"]:
                    continue
                # 与现有数据保持一致的 id 格式："{subject_id}|{char_name}"
                char_id = f"{sid}|{char['name']}"
                if char_id in seen_char_ids:
                    continue
                seen_char_ids.add(char_id)
                char_records.append({
                    "char_id": char_id,
                    "anime_id": sid,
                    "name":    char["name"],
                    "name_cn": char["name_cn"],
                })

        print(f"[5/6] 写入 {len(char_records):,} 个 Character 节点 + HAS_CHARACTER 关系...")
        for batch in batches(char_records, BATCH):
            s.run(_Q_CHAR, records=batch)
        print("  完成")

        # 6. VOICED_BY
        va_records: list[dict] = []

        for (cid, sid), pid in va_map.items():
            if pid not in person_map:
                continue
            va = person_map[pid]
            if not va["name"]:
                continue
            char = char_map.get(cid)
            if not char or not char["name"]:
                continue
            char_id = f"{sid}|{char['name']}"
            if char_id not in seen_char_ids:
                continue
            va_records.append({
                "char_id": char_id,
                "va_name": va["name"],
            })

        print(f"[6/6] 写入 {len(va_records):,} 条 VOICED_BY 关系...")
        for batch in batches(va_records, BATCH):
            s.run(_Q_VA, records=batch)
        print("  完成")


# ─── 步骤五：去重检查 + 统计 ───────────────────────────────────────
def dedup_check(driver, db):
    print("\n===== 去重检查 =====")
    with driver.session(database=db) as s:

        # Anime 重复检查
        rows = s.run("""
            MATCH (a:Anime) WHERE a.id IS NOT NULL
            WITH a.id AS id, count(*) AS cnt
            WHERE cnt > 1
            RETURN id, cnt ORDER BY cnt DESC LIMIT 10
        """).data()
        if rows:
            print(f"⚠️  Anime 重复: {len(rows)} 个 id")
            for r in rows:
                print(f"  id={r['id']}  出现 {r['cnt']} 次")
        else:
            print("✅ Anime 无重复")

        # Character 重复检查
        rows2 = s.run("""
            MATCH (c:Character) WHERE c.id IS NOT NULL
            WITH c.id AS id, count(*) AS cnt
            WHERE cnt > 1
            RETURN id, cnt ORDER BY cnt DESC LIMIT 5
        """).data()
        if rows2:
            print(f"⚠️  Character 重复: {len(rows2)} 个 id")
            for r in rows2:
                print(f"  id={r['id']}  出现 {r['cnt']} 次")
        else:
            print("✅ Character 无重复")

        # 节点总量统计
        stat = s.run("""
            MATCH (n)
            RETURN labels(n)[0] AS label, count(*) AS cnt
            ORDER BY cnt DESC
        """).data()
        print("\n当前节点统计：")
        total = 0
        for r in stat:
            print(f"  {r['label']:15s}: {r['cnt']:,}")
            total += r["cnt"]
        print(f"  {'合计':15s}: {total:,}  （上限 200,000）")

        # 关系统计
        rel_stat = s.run("""
            MATCH ()-[r]->()
            RETURN type(r) AS rel, count(*) AS cnt
            ORDER BY cnt DESC
        """).data()
        print("\n当前关系统计：")
        total_rel = 0
        for r in rel_stat:
            print(f"  {r['rel']:20s}: {r['cnt']:,}")
            total_rel += r["cnt"]
        print(f"  {'合计':20s}: {total_rel:,}  （上限 400,000）")


# ─── 主流程 ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",     action="store_true", help="预览，不写入数据库")
    parser.add_argument("--dedup-check", action="store_true", help="只做去重检查，不导入")
    args = parser.parse_args()

    if not ARCHIVE.exists():
        raise FileNotFoundError(f"Archive 不存在: {ARCHIVE}")

    driver, db = get_driver()
    print(f"已连接 Neo4j (database={db})\n")

    if args.dedup_check:
        dedup_check(driver, db)
        driver.close()
        return

    # 1. 现有 ID
    existing_ids = get_existing_ids(driver, db)

    # 2. 扫描主表
    anime_list, qualifying_ids = scan_subjects(existing_ids)
    if not anime_list:
        print("没有符合条件的新 anime，退出")
        driver.close()
        return

    # 3. 扫描角色 / 声优
    char_map, subj_chars, va_map, person_map = scan_characters(qualifying_ids)

    # 4. 写入（或 dry run）
    write_to_neo4j(driver, db, anime_list, char_map, subj_chars,
                   va_map, person_map, args.dry_run)

    # 5. 去重检查（实际写入后才做）
    if not args.dry_run:
        dedup_check(driver, db)

    driver.close()
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
