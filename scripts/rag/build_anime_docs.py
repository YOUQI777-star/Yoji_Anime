import json
import math
import pandas as pd
from pathlib import Path

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
OUT_FILE = DATA_DIR / "anime_docs.jsonl"

ANIME_FILE = DATA_DIR / "anime_general_info_clean.csv"
if not ANIME_FILE.exists():
    ANIME_FILE = DATA_DIR / "anime_master.csv"

anime = pd.read_csv(ANIME_FILE)
tag = pd.read_csv(DATA_DIR / "anime_tag_clean.csv")
char = pd.read_csv(DATA_DIR / "anime_character_clean.csv")
rel = pd.read_csv(DATA_DIR / "anime_relations_clean.csv")


def safe_str(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def safe_num(x):
    if pd.isna(x):
        return None
    return x


def unique_keep_order(values):
    seen = set()
    result = []
    for v in values:
        v = safe_str(v)
        if not v or v in seen:
            continue
        seen.add(v)
        result.append(v)
    return result


def top_n(values, n=10):
    return unique_keep_order(values)[:n]


# ===== 预聚合 =====

tags_map = (
    tag.groupby("anime_id")["tag"]
    .apply(list)
    .to_dict()
)

char_name_map = (
    char.groupby("anime_id")["character"]
    .apply(list)
    .to_dict()
)

cv_map = (
    char.groupby("anime_id")["cv"]
    .apply(list)
    .to_dict()
)

rel_name_map = (
    rel.groupby("source_id")["target_name_cn"]
    .apply(list)
    .to_dict()
)

rel_name_fallback_map = (
    rel.groupby("source_id")["target_name"]
    .apply(list)
    .to_dict()
)


def build_doc_text(row):
    anime_id = row["anime_id"]

    title = safe_str(row["title_display"])
    title_ja = safe_str(row["name_ja"])
    title_cn = safe_str(row["name_cn"])
    date = safe_str(row["date"])
    country = safe_str(row["country"])
    platform = safe_str(row["platform"])
    studio = safe_str(row["studio"])
    director = safe_str(row["director"])
    summary = safe_str(row["summary"])

    score = safe_num(row["score"])
    rank = safe_num(row["rank"])
    episodes = safe_num(row["episodes"])

    tags = top_n(tags_map.get(anime_id, []), 12)
    characters = top_n(char_name_map.get(anime_id, []), 10)
    voice_actors = top_n(cv_map.get(anime_id, []), 10)

    related_cn = unique_keep_order(rel_name_map.get(anime_id, []))
    related_jp = unique_keep_order(rel_name_fallback_map.get(anime_id, []))

    related = [x for x in related_cn if x]
    if len(related) < 10:
        for x in related_jp:
            if x and x not in related:
                related.append(x)
            if len(related) >= 10:
                break

    parts = []

    # 1. 基本信息
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
    if episodes is not None and not (isinstance(episodes, float) and math.isnan(episodes)):
        basic += f" 集数：{int(episodes) if float(episodes).is_integer() else episodes}。"
    if studio:
        basic += f" 制作公司：{studio}。"
    if director:
        basic += f" 导演：{director}。"
    if score is not None and not (isinstance(score, float) and math.isnan(score)):
        basic += f" 评分：{score}。"
    if rank is not None and not (isinstance(rank, float) and math.isnan(rank)):
        basic += f" 排名：{int(rank) if float(rank).is_integer() else rank}。"

    parts.append(basic)

    # 2. 简介
    if summary:
        parts.append(f"剧情简介：{summary}")

    # 3. 标签
    if tags:
        parts.append("标签：" + "、".join(tags) + "。")

    # 4. 角色
    if characters:
        parts.append("主要角色：" + "、".join(characters) + "。")

    # 5. 声优
    if voice_actors:
        parts.append("相关声优：" + "、".join(voice_actors) + "。")

    # 6. 关联作品
    if related:
        parts.append("关联作品：" + "、".join(related) + "。")

    return "\n".join(parts), tags, characters, voice_actors, related


docs_written = 0

with open(OUT_FILE, "w", encoding="utf-8") as f:
    for _, row in anime.iterrows():
        text, tags, characters, voice_actors, related = build_doc_text(row)

        record = {
            "doc_id": f"anime_{int(row['anime_id'])}",
            "entity_type": "Anime",
            "entity_id": int(row["anime_id"]),
            "title": safe_str(row["title_display"]),
            "title_ja": safe_str(row["name_ja"]),
            "title_cn": safe_str(row["name_cn"]),
            "metadata": {
                "date": safe_str(row["date"]),
                "country": safe_str(row["country"]),
                "platform": safe_str(row["platform"]),
                "score": None if pd.isna(row["score"]) else float(row["score"]),
                "rank": None if pd.isna(row["rank"]) else int(row["rank"]),
                "episodes": None if pd.isna(row["episodes"]) else float(row["episodes"]),
                "studio": safe_str(row["studio"]),
                "director": safe_str(row["director"]),
                "tags": tags,
                "characters": characters,
                "voice_actors": voice_actors,
                "related_works": related,
            },
            "text": text
        }

        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        docs_written += 1

print(f"anime_docs written: {docs_written}")
print(f"output: {OUT_FILE}")
