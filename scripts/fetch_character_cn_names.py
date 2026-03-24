"""
fetch_character_cn_names.py
────────────────────────────────────────────────────────────────
读取 anime_character_cleaned.csv，对每个唯一的日文角色名
通过 Bangumi API 查询其中文名（name_cn），
直接更新 character_cn_cache.json（断点续传，不重复请求）。

使用方法：
    python fetch_character_cn_names.py
"""

import csv
import json
import os
import time
import requests

# ── 配置 ────────────────────────────────────────────────────────
TOKEN      = "luqUxFzq9aq8CoUgsT9R8cPqEzcLrgBuujendCu6"
INPUT_CSV  = "/Users/wangyouqi/Desktop/Yoji_Anime/data/anime_character_cleaned.csv"
CACHE_FILE = "/Users/wangyouqi/Desktop/Yoji_Anime/data/character_cn_cache.json"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
    "User-Agent":    "anime-kg-research"
}

SEARCH_URL = "https://api.bgm.tv/v0/search/characters"
SLEEP_OK   = 0.4
SLEEP_ERR  = 3.0
MAX_RETRY  = 3
SAVE_EVERY = 50
# ────────────────────────────────────────────────────────────────


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def parse_infobox_value(value) -> str:
    if isinstance(value, list):
        return " / ".join(v.get("v", "") for v in value if isinstance(v, dict) and v.get("v"))
    return str(value)


def fetch_cn_name(jp_name: str) -> str:
    payload = {"keyword": jp_name, "filter": {}, "limit": 5, "offset": 0}

    for attempt in range(MAX_RETRY):
        try:
            r = requests.post(SEARCH_URL, headers=HEADERS,
                              json=payload, timeout=10)
            if r.status_code == 429:
                print(f"  [rate-limit] sleeping {SLEEP_ERR}s...")
                time.sleep(SLEEP_ERR)
                continue
            if r.status_code != 200:
                return ""

            data = r.json().get("data", [])
            if not data:
                return ""

            # 模糊匹配：包含关系优先，找不到取第一个
            match = next(
                (d for d in data
                 if jp_name in d.get("name", "") or d.get("name", "") in jp_name),
                data[0]
            )

            # 优先取 name_cn 字段
            cn = match.get("name_cn", "").strip()

            # 再从 infobox 找
            if not cn:
                for item in match.get("infobox", []):
                    key = item.get("key", "")
                    if key in ("简体中文名", "中文名", "Chinese name", "中文名称"):
                        cn = parse_infobox_value(item.get("value", "")).strip()
                        break

            return cn

        except Exception as e:
            print(f"  [err] {jp_name}: {e}  (attempt {attempt+1}/{MAX_RETRY})")
            time.sleep(SLEEP_ERR)

    return ""


def main():
    # 1. 读取角色 CSV
    print(f"Reading {INPUT_CSV}...")
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows)} rows loaded")

    # 2. 收集唯一日文角色名
    unique_names = sorted(set(r["character"] for r in rows if r.get("character")))
    print(f"  {len(unique_names)} unique character names")

    # 3. 加载已有 cache，跳过已查过的（包括查过但为空的）
    cache = load_cache()
    todo = [n for n in unique_names if not cache.get(n, "").strip()]
    print(f"  {len(cache)} already in cache, {len(todo)} remaining\n")

    # 4. 逐个抓取
    total = len(todo)
    for i, name in enumerate(todo):
        cn = fetch_cn_name(name)
        cache[name] = cn

        status = f"✓ {cn}" if cn else "—"
        print(f"  [{i+1:>6}/{total}] {name:<35}  ->  {status}")

        if (i + 1) % SAVE_EVERY == 0:
            save_cache(cache)
            print(f"  [cache saved at {i+1}]")

        time.sleep(SLEEP_OK)

    save_cache(cache)
    filled = sum(1 for v in cache.values() if v.strip())
    print(f"\nDone. {filled}/{len(cache)} entries have a Chinese name")
    print(f"Cache: {CACHE_FILE}")
    print(f"\nNext: run data_cleaning.py again to apply CN names to the CSV.")


if __name__ == "__main__":
    main()
