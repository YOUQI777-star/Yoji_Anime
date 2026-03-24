"""
crawl_anime_continued.py
────────────────────────────────────────────────────────────────
从 ID 244348 继续爬取 Bangumi 动漫数据。
只保留有排名的动漫（过滤冷门/短片/同人）。
直接追加写入原有 CSV 文件。

输出：
  /Users/wangyouqi/anime_info_new.csv       — 追加写入
  /Users/wangyouqi/anime_character_new.csv  — 追加写入
  /Users/wangyouqi/crawl_progress.json      — 断点续传

用法：
  python crawl_anime_continued.py
  （中断后直接重跑，自动从断点继续）
"""

import csv
import json
import os
import time
import requests

# ── 配置 ────────────────────────────────────────────────────────
TOKEN            = "luqUxFzq9aq8CoUgsT9R8cPqEzcLrgBuujendCu6"
DEFAULT_START_ID = 244348
MAX_ID           = 400000
MAX_NEW_ANIME    = 6000

INFO_CSV      = "/Users/wangyouqi/anime_info_new.csv"
CHAR_CSV      = "/Users/wangyouqi/anime_character_new.csv"
PROGRESS_FILE = "/Users/wangyouqi/crawl_progress.json"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent":    "anime-kg-research-v2",
    "Content-Type":  "application/json"
}
SLEEP_OK   = 0.5
SLEEP_CHAR = 0.3
SLEEP_ERR  = 3.0
MAX_RETRY  = 3
# ────────────────────────────────────────────────────────────────

COUNTRY_MAP = {
    "日本": "Japan", "japan": "Japan", "JP": "Japan",
    "中国": "China", "中华人民共和国": "China", "china": "China",
    "大陆": "China", "内地": "China", "中国大陆": "China",
    "美国": "USA", "美利坚": "USA", "usa": "USA", "united states": "USA",
    "台湾": "Taiwan", "台灣": "Taiwan", "taiwan": "Taiwan",
    "韩国": "Korea", "韓國": "Korea", "south korea": "Korea", "korea": "Korea",
    "法国": "France", "france": "France",
    "英国": "UK", "united kingdom": "UK", "uk": "UK",
    "德国": "Germany", "germany": "Germany",
    "加拿大": "Canada", "canada": "Canada",
}

COUNTRY_KEYS  = {"制作国", "国家", "地区", "制作地区", "country", "制作国家"}
STUDIO_KEYS   = {"动画制作", "制作公司", "动画公司", "制作", "アニメーション制作", "制作スタジオ"}
DIRECTOR_KEYS = {"导演", "监督", "原作", "总导演"}


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": DEFAULT_START_ID - 1, "anime_count": 0}


def save_progress(last_id: int, anime_count: int):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id, "anime_count": anime_count}, f)


def parse_infobox_value(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("v", ""))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(p for p in parts if p).strip()
    return ""


def parse_infobox(infobox: list) -> dict:
    studio = director = country_raw = ""
    for item in infobox:
        key = item.get("key", "").strip()
        val = parse_infobox_value(item.get("value", ""))
        if not val:
            continue
        key_lower = key.lower()
        if key in STUDIO_KEYS or key_lower in {k.lower() for k in STUDIO_KEYS}:
            if not studio:
                studio = val.split()[0]
        if key in DIRECTOR_KEYS or key_lower in {k.lower() for k in DIRECTOR_KEYS}:
            if not director:
                director = val.split()[0]
        if key in COUNTRY_KEYS or key_lower in {k.lower() for k in COUNTRY_KEYS}:
            if not country_raw:
                country_raw = val
    return {"studio": studio, "director": director, "country_raw": country_raw}


def infer_country_from_tags(tags: list) -> str:
    all_tags = " ".join(t.get("name", "") for t in tags).lower()
    for kw in ["中国", "国产", "国漫", "bilibili", "b站", "国产动画"]:
        if kw in all_tags:
            return "China"
    for kw in ["美国", "美漫", "dc", "marvel", "cartoon network", "disney"]:
        if kw in all_tags:
            return "USA"
    return ""


def normalize_country(raw: str) -> str:
    if not raw:
        return ""
    raw_lower = raw.strip().lower()
    for key, val in COUNTRY_MAP.items():
        if key.lower() in raw_lower:
            return val
    return raw.strip()


def fetch_subject(sid: int):
    url = f"https://api.bgm.tv/v0/subjects/{sid}"
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                print(f"  [rate-limit] sleeping {SLEEP_ERR}s")
                time.sleep(SLEEP_ERR)
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except Exception as e:
            print(f"  [err] subject {sid}: {e} (attempt {attempt+1})")
            time.sleep(SLEEP_ERR)
    return None


def fetch_characters(sid: int) -> list:
    url = f"https://api.bgm.tv/v0/subjects/{sid}/characters"
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 404:
                return []
            if r.status_code == 429:
                time.sleep(SLEEP_ERR)
                continue
            if r.status_code != 200:
                return []

            chars = []
            for item in r.json():
                char_name_jp = item.get("name", "").strip()
                char_name_cn = item.get("name_cn", "").strip()

                if not char_name_cn:
                    for ib in item.get("infobox", []):
                        if ib.get("key", "") in ("简体中文名", "中文名", "Chinese name", "中文名称"):
                            char_name_cn = parse_infobox_value(ib.get("value", ""))
                            break

                relation_val = item.get("relation", "")
                if isinstance(relation_val, int):
                    relation_str = {1: "主角", 2: "配角", 3: "客串"}.get(relation_val, str(relation_val))
                else:
                    relation_str = str(relation_val).replace("|", "").strip()

                actors = item.get("actors", [])
                if not actors:
                    if char_name_jp:
                        chars.append({
                            "character": char_name_jp,
                            "name_cn": char_name_cn,
                            "cv": "",
                            "relation": relation_str
                        })
                else:
                    for actor in actors:
                        if char_name_jp:
                            chars.append({
                                "character": char_name_jp,
                                "name_cn": char_name_cn,
                                "cv": actor.get("name", "").strip(),
                                "relation": relation_str
                            })
            return chars

        except Exception as e:
            print(f"  [err] characters {sid}: {e} (attempt {attempt+1})")
            time.sleep(SLEEP_ERR)
    return []


def init_csv_files():
    """文件存在就追加，不存在就新建并写表头"""
    if not os.path.exists(INFO_CSV):
        with open(INFO_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                "id", "name", "name_cn", "date", "platform",
                "score", "rank", "episodes",
                "studio", "director", "country", "tags", "summary"
            ])
        print(f"Created new file: {INFO_CSV}")
    else:
        print(f"Appending to existing: {INFO_CSV}")

    if not os.path.exists(CHAR_CSV):
        with open(CHAR_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                "subject_id", "anime", "country",
                "character", "name_cn", "cv", "relation"
            ])
        print(f"Created new file: {CHAR_CSV}")
    else:
        print(f"Appending to existing: {CHAR_CSV}")


def main():
    progress    = load_progress()
    start_id    = progress["last_id"] + 1
    anime_count = progress["anime_count"]

    print(f"Starting from ID : {start_id}")
    print(f"Anime collected  : {anime_count} (this session)")
    print(f"Will stop after  : {MAX_NEW_ANIME} new anime")
    print()

    init_csv_files()
    print()

    for sid in range(start_id, MAX_ID + 1):
        if anime_count >= MAX_NEW_ANIME:
            print(f"\nReached limit of {MAX_NEW_ANIME}. Stopping.")
            break

        data = fetch_subject(sid)

        if not data:
            save_progress(sid, anime_count)
            continue

        # 只要动漫
        if data.get("type") != 2:
            save_progress(sid, anime_count)
            continue

        # 只要有排名的（有名的）
        rank = data.get("rating", {}).get("rank")
        if not rank:
            save_progress(sid, anime_count)
            continue

        name     = data.get("name", "")
        name_cn  = data.get("name_cn", "")
        date     = data.get("date", "")
        platform = data.get("platform", "")
        score    = data.get("rating", {}).get("score", "")
        episodes = data.get("total_episodes", "")
        summary  = data.get("summary", "").replace("\n", " ").strip()
        tags     = ",".join(t["name"] for t in data.get("tags", []))

        infobox_data = parse_infobox(data.get("infobox", []))
        studio   = infobox_data["studio"]
        director = infobox_data["director"]

        country = normalize_country(infobox_data["country_raw"])
        if not country:
            country = infer_country_from_tags(data.get("tags", []))
        if not country:
            country = "Japan"

        with open(INFO_CSV, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                sid, name, name_cn, date, platform,
                score, rank, episodes,
                studio, director, country, tags, summary
            ])

        time.sleep(SLEEP_CHAR)
        chars = fetch_characters(sid)

        if chars:
            with open(CHAR_CSV, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                for c in chars:
                    writer.writerow([
                        sid, name_cn or name, country,
                        c["character"], c["name_cn"], c["cv"], c["relation"]
                    ])

        anime_count += 1
        save_progress(sid, anime_count)

        print(f"[{anime_count:>5}/{MAX_NEW_ANIME}] ID {sid:>6}  "
              f"{(name_cn or name)[:28]:<28}  "
              f"country={country:<8}  chars={len(chars)}")

        time.sleep(SLEEP_OK)

    print(f"\nDone. Total collected: {anime_count}")


if __name__ == "__main__":
    main()