"""
data_cleaning.py
────────────────────────────────────────────────────────────────
对 anime_info_new.csv 和 anime_character_new.csv 做全面清洗：

  0. 去重（按 id 去重）
  1. 删除 episodes=0 或空的动漫
  2. 用原名语言识别国家（替代之前只有 Japan/China/USA 的问题）
  3. Tag 标准化（和之前 anime_info_country_cleaned.csv 相同处理）
  4. 角色中文名：用 character_cn_cache.json 补充 name_cn 为空的行
             同时把新出现的角色名追加写入 cache（供后续继续抓）

输出：
  anime_info_cleaned.csv
  anime_character_cleaned.csv
  character_cn_cache.json  （更新，追加新角色名）

用法：
  把本脚本放到 Yoji_Anime/scripts/
  确保以下文件存在：
    /Users/wangyouqi/anime_info_new.csv
    /Users/wangyouqi/anime_character_new.csv
    /Users/wangyouqi/character_cn_cache.json   （之前生成的）
  python data_cleaning.py
"""

import csv
import json
import os
import re
import unicodedata

# ── 路径配置 ─────────────────────────────────────────────────────
INFO_IN    = "/Users/wangyouqi/Desktop/Yoji_Anime/data/anime_info_new.csv"
CHAR_IN    = "/Users/wangyouqi/Desktop/Yoji_Anime/data/anime_character_new.csv"
CACHE_FILE = "/Users/wangyouqi/Desktop/Yoji_Anime/data/crawl_progress.json"   # 之前生成的 JSON

INFO_OUT   = "/Users/wangyouqi/Desktop/Yoji_Anime/data/anime_info_cleaned.csv"
CHAR_OUT   = "/Users/wangyouqi/Desktop/Yoji_Anime/data/anime_character_cleaned.csv"
# ────────────────────────────────────────────────────────────────


# ════════════════════════════════════════════════════════════════
# 2. 语言识别 → 国家
# 规则：
#   - name 含日文假名     → 已经是 Japan，不动
#   - name 含汉字         → 已经是 China/Japan，不动
#   - name 是纯英文       → 已经是 USA/Japan，不动
#   - name 含其他语言字符 → 按优先级修正：
#       法语词缀 > 韩文 > 泰文 > 阿拉伯 > 西里尔（俄语）
# ════════════════════════════════════════════════════════════════

# 法语常见冠词/词缀/特殊字符
FRENCH_PATTERNS = [
    r'\bLe\b', r'\bLa\b', r'\bLes\b', r"\bL'",
    r'\bUn\b', r'\bUne\b', r'\bDes\b', r'\bDu\b',
    r'\bMon\b', r'\bMa\b', r'\bSon\b', r'\bSa\b',
    r'\bEt\b', r'\bEn\b', r'\bAu\b', r'\bAux\b',
    r'\bQui\b', r'\bQue\b', r'\bPour\b',
    r'[àâäéèêëîïôùûüçœæÀÂÄÉÈÊËÎÏÔÙÛÜÇŒÆ]',
]


def infer_country(row: dict) -> str:
    """
    修正 country 字段。
    日文/中文/英文的动漫保持不变，只对其他语言进行修正。
    修正优先级：法语 > 韩文 > 泰文 > 阿拉伯 > 西里尔(俄语)
    """
    name     = row.get("name", "")
    existing = row.get("country", "").strip()

    # 字符集检测
    has_hiragana = bool(re.search(r'[\u3040-\u309F]', name))
    has_katakana = bool(re.search(r'[\u30A0-\u30FF]', name))
    has_kanji    = bool(re.search(r'[\u4E00-\u9FFF]', name))
    has_korean   = bool(re.search(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]', name))
    has_thai     = bool(re.search(r'[\u0E00-\u0E7F]', name))
    has_arabic   = bool(re.search(r'[\u0600-\u06FF\u0750-\u077F]', name))
    has_cyrillic = bool(re.search(r'[\u0400-\u04FF]', name))

    # 含日文假名 → Japan，不改
    if has_hiragana or has_katakana:
        return "Japan"

    # 含汉字（无假名）→ 保持现有不改（China 或 Japan 都正确）
    if has_kanji:
        return existing if existing else "Japan"

    # 含韩文 → Korea
    if has_korean:
        return "Korea"

    # 含泰文 → Thailand
    if has_thai:
        return "Thailand"

    # 含阿拉伯文 → Middle East
    if has_arabic:
        return "Middle East"

    # 含西里尔字母 → Russia
    if has_cyrillic:
        return "Russia"

    # 拉丁字母：检查是否含法语特征
    is_french = any(re.search(p, name) for p in FRENCH_PATTERNS)
    if is_french:
        return "France"

    # 其他情况（纯英文/罗马字等）→ 保持现有不改
    return existing if existing else "Japan"

# ════════════════════════════════════════════════════════════════
# 3. Tag 标准化（与 info_clean.pdf 里的处理逻辑相同）
# ════════════════════════════════════════════════════════════════

TAG_MAP = {
    # GL / 百合
    "GL": "GL", "百合": "GL", "yuri": "GL",
    # BL / 耽美
    "BL": "BL", "耽美": "BL", "腐": "BL", "yaoi": "BL", "男男": "BL",
    # 恋爱
    "恋爱": "恋爱", "爱情": "恋爱", "romance": "恋爱",
    # 校园
    "校园": "校园", "学校": "校园", "school": "校园", "高校": "校园",
    # 日常
    "日常": "日常", "slice of life": "日常", "日常系": "日常",
    # 科幻
    "科幻": "科幻", "SF": "科幻", "Sci-Fi": "科幻", "sci-fi": "科幻",
    "science fiction": "科幻", "赛博朋克": "科幻", "机甲": "科幻",
    # 奇幻
    "奇幻": "奇幻", "fantasy": "奇幻", "异世界": "奇幻",
    "isekai": "奇幻", "魔法": "奇幻",
    # 战斗
    "战斗": "战斗", "动作": "战斗", "action": "战斗", "热血": "战斗",
    "格斗": "战斗",
    # 冒险
    "冒险": "冒险", "adventure": "冒险",
    # 悬疑
    "悬疑": "悬疑", "推理": "悬疑", "mystery": "悬疑", "侦探": "悬疑",
    # 恐怖
    "恐怖": "恐怖", "horror": "恐怖", "惊悚": "恐怖",
    # 搞笑
    "搞笑": "搞笑", "喜剧": "搞笑", "comedy": "搞笑", "轻松": "搞笑",
    # 治愈
    "治愈": "治愈", "温馨": "治愈", "healing": "治愈",
    # 运动
    "运动": "运动", "sports": "运动", "体育": "运动",
    # 音乐
    "音乐": "音乐", "music": "音乐", "偶像": "音乐",
    # 历史
    "历史": "历史", "historical": "历史", "时代剧": "历史",
    # 机战
    "机战": "机战", "mecha": "机战", "机器人": "机战",
    # 魔法少女
    "魔法少女": "魔法少女",
    # 后宫
    "后宫": "后宫", "harem": "后宫",
    # 原创
    "原创": "原创", "original": "原创",
    # 漫改
    "漫改": "漫改", "漫画改": "漫改", "漫画改编": "漫改",
    "manga": "漫改", "漫画": "漫改",
    # 小说改
    "小说改": "小说改", "轻小说": "小说改", "light novel": "小说改",
    "LN": "小说改",
    # 游戏改
    "游戏改": "游戏改", "游戏改编": "游戏改", "galgame": "游戏改",
    "GAL": "游戏改", "visual novel": "游戏改",
    # 平台类型
    "TV": "TV", "TVA": "TV",
    "Movie": "Movie", "剧场版": "Movie", "电影": "Movie",
    "OVA": "OVA", "OAD": "OVA",
    "WEB": "WEB",
    # 国家（保留在 tag 里方便筛选）
    "日本": "日本动画", "日本动画": "日本动画",
    "中国": "中国动画", "国产": "中国动画", "国漫": "中国动画",
    "美国": "美国动画",
}

def standardize_tags(tag_str: str) -> list:
    """把原始 tag 字符串标准化，返回去重后的标准 tag 列表"""
    if not tag_str:
        return []
    result = set()
    for t in tag_str.split(","):
        t = t.strip()
        if t in TAG_MAP:
            result.add(TAG_MAP[t])
        # 大小写不敏感匹配
        elif t.lower() in {k.lower(): v for k, v in TAG_MAP.items()}:
            lower_map = {k.lower(): v for k, v in TAG_MAP.items()}
            result.add(lower_map[t.lower()])
    return sorted(result)


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

def main():

    # ── 0+1+2+3. 清洗 anime_info ────────────────────────────────
    print(f"Reading {INFO_IN}…")
    with open(INFO_IN, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows)} rows loaded")

    # 0. 去重
    seen_ids = set()
    deduped = []
    for r in rows:
        rid = r.get("id", "").strip()
        if rid not in seen_ids:
            seen_ids.add(rid)
            deduped.append(r)
    print(f"  After dedup: {len(deduped)} rows ({len(rows)-len(deduped)} removed)")

    # 1. 删除 episodes=0 或空
    valid = []
    removed_ep = 0
    for r in deduped:
        ep = str(r.get("episodes", "")).strip()
        if ep in ("0", "", "None"):
            removed_ep += 1
            continue
        valid.append(r)
    print(f"  After removing episodes=0/empty: {len(valid)} rows ({removed_ep} removed)")

    # 2+3. 修正国家 + 标准化 tags
    for r in valid:
        r["country"] = infer_country(r)
        r["tags"]    = ",".join(standardize_tags(r.get("tags", "")))

    # 统计国家分布
    country_dist = {}
    for r in valid:
        c = r["country"]
        country_dist[c] = country_dist.get(c, 0) + 1
    print(f"  Country distribution: {dict(sorted(country_dist.items(), key=lambda x:-x[1]))}")

    # 写出
    fieldnames = list(valid[0].keys())
    with open(INFO_OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(valid)
    print(f"  Written: {INFO_OUT}\n")


    # ── 4. 清洗 anime_character + 补充中文名 ────────────────────
    print(f"Reading {CHAR_IN}…")
    with open(CHAR_IN, encoding="utf-8-sig") as f:
        char_rows = list(csv.DictReader(f))
    print(f"  {len(char_rows)} rows loaded")

    # 只保留属于清洗后动漫的角色
    valid_ids = seen_ids
    char_rows = [r for r in char_rows if r.get("subject_id","").strip() in valid_ids]
    print(f"  After filtering by valid anime IDs: {len(char_rows)} rows")

    # 去重（同一动漫+角色+声优）
    seen_chars = set()
    char_deduped = []
    for r in char_rows:
        key = (r.get("subject_id",""), r.get("character",""), r.get("cv",""))
        if key not in seen_chars:
            seen_chars.add(key)
            char_deduped.append(r)
    print(f"  After dedup: {len(char_deduped)} rows")

    # 加载已有的 cache
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"  Cache loaded: {len(cache)} entries ({sum(1 for v in cache.values() if v)} with CN name)")
    else:
        print(f"  No cache file found at {CACHE_FILE}, will create new one")

    # 补充中文名：用 cache 填充 name_cn 为空的行
    filled = 0
    new_names = 0
    for r in char_deduped:
        jp = r.get("character", "").strip()
        if not jp:
            continue

        # 如果 name_cn 已有，直接跳过
        if r.get("name_cn", "").strip():
            # 也更新到 cache
            if jp not in cache:
                cache[jp] = r["name_cn"]
            continue

        # 从 cache 里找
        cn = cache.get(jp, None)
        if cn is not None:
            r["name_cn"] = cn
            if cn:
                filled += 1
        else:
            # 新角色名，加入 cache 但值为空（留给后续抓取脚本填充）
            cache[jp] = ""
            new_names += 1

    print(f"  Filled {filled} CN names from cache")
    print(f"  {new_names} new character names added to cache (need fetching)")

    # 更新 cache 文件
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"  Cache updated: {CACHE_FILE} ({len(cache)} total entries)")

    # 确保 name_cn 列存在
    for r in char_deduped:
        if "name_cn" not in r:
            r["name_cn"] = ""

    # 写出
    char_fields = ["subject_id", "anime", "country", "character", "name_cn", "cv", "relation"]
    with open(CHAR_OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=char_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(char_deduped)
    print(f"  Written: {CHAR_OUT}\n")

    print("=" * 50)
    print("All done!")
    print(f"  {INFO_OUT}")
    print(f"  {CHAR_OUT}")
    print(f"  {CACHE_FILE}  ← run fetch_character_cn_names.py again to fill new entries")
    print("=" * 50)


if __name__ == "__main__":
    main()
