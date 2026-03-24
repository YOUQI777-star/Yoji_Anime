"""
crawl_series_relations.py
────────────────────────────────────────────────────────────────
读取 HERE_anime_info.csv，对每个 Bangumi ID 调用
/v0/subjects/{id}/subjects 接口，爬取同系列关系。

输出：
  /Users/wangyouqi/Desktop/Yoji_Anime/data/anime_relations.csv
  /Users/wangyouqi/Desktop/Yoji_Anime/data/relations_progress.json  (断点续传)

用法：
  python crawl_series_relations.py
"""

import csv, json, os, time, requests

TOKEN     = "luqUxFzq9aq8CoUgsT9R8cPqEzcLrgBuujendCu6"
INPUT_CSV = "/Users/wangyouqi/Desktop/Yoji_Anime/data/HERE.anime_info.csv"
OUT_CSV   = "/Users/wangyouqi/Desktop/Yoji_Anime/data/anime_relations.csv"
PROGRESS  = "/Users/wangyouqi/Desktop/Yoji_Anime/data/relations_progress.json"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "anime-kg-research-v2",
}

# 只有这些关系类型才归入同一系列
SAME_SERIES = {3, 4, 5, 6, 7, 8}  # 续集/前传/正传/番外/剧场版/衍生
REL_NAMES   = {3:"续集", 4:"前传", 5:"正传", 6:"番外", 7:"剧场版", 8:"衍生",
               1:"改编", 2:"原作", 99:"其他"}

SLEEP_OK  = 0.4
SLEEP_ERR = 3.0
MAX_RETRY = 3
SAVE_EVERY = 100


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as f:
            return set(json.load(f).get("done_ids", []))
    return set()

def save_progress(done):
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump({"done_ids": list(done)}, f)

def fetch_relations(sid):
    url = f"https://api.bgm.tv/v0/subjects/{sid}/subjects"
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 404: return []
            if r.status_code == 429:
                time.sleep(SLEEP_ERR); continue
            if r.status_code != 200: return []
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"  [err] {sid}: {e} (attempt {attempt+1})")
            time.sleep(SLEEP_ERR)
    return []


def main():
    # 读取所有 ID
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        anime_ids = [r["id"].strip() for r in csv.DictReader(f) if r.get("id","").strip()]
    print(f"Total IDs: {len(anime_ids)}")

    done = load_progress()
    todo = [i for i in anime_ids if i not in done]
    print(f"Already done: {len(done)}, remaining: {len(todo)}")

    # 初始化输出文件
    file_exists = os.path.exists(OUT_CSV)
    out = open(OUT_CSV, "a", newline="", encoding="utf-8-sig")
    writer = csv.writer(out)
    if not file_exists:
        writer.writerow(["source_id","target_id","target_name","target_name_cn",
                         "relation_type","relation_name","same_series"])

    total = len(todo)
    for i, sid in enumerate(todo):
        rels = fetch_relations(int(sid))

        for item in rels:
            # 只要动漫类型 (type=2)
            if item.get("type", 0) != 2:
                continue
            rel_type = item.get("relation", 0)
            rel_name = REL_NAMES.get(rel_type, "未知")
            same     = 1 if rel_type in SAME_SERIES else 0
            writer.writerow([
                sid,
                item.get("id", ""),
                item.get("name", ""),
                item.get("name_cn", ""),
                rel_type, rel_name, same
            ])

        done.add(sid)

        if rels:
            print(f"  [{i+1:>5}/{total}] ID {sid}  → {len(rels)} relations")

        if (i + 1) % SAVE_EVERY == 0:
            out.flush()
            save_progress(done)
            print(f"  [saved at {i+1}]")

        time.sleep(SLEEP_OK)

    out.close()
    save_progress(done)
    print(f"\nDone. Output: {OUT_CSV}")
    print("Next: run build_series.py")


if __name__ == "__main__":
    main()
