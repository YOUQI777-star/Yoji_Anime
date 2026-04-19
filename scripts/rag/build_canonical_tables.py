import pandas as pd
from pathlib import Path

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "READY_VERSION"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

def resolve_file(filename: str) -> Path:
    p = DATA_DIR / filename
    if p.exists():
        return p
    raise FileNotFoundError(f"Cannot find {filename} in {DATA_DIR}")

# 1. 读取原始数据
anime = pd.read_csv(resolve_file("anime_general_info.csv"))
char = pd.read_csv(resolve_file("anime_character.csv"))
tag = pd.read_csv(resolve_file("anime_tag.csv"))
rel = pd.read_csv(resolve_file("anime_relations.csv"))

# 2. 主表标准化
anime = anime.rename(columns={
    "id": "anime_id",
    "name": "name_ja"
}).copy()

anime["name_cn"] = anime["name_cn"].fillna("")
anime["studio"] = anime["studio"].fillna("")
anime["director"] = anime["director"].fillna("")
anime["summary"] = anime["summary"].fillna("")
anime["date"] = anime["date"].fillna("")

anime["title_display"] = anime.apply(
    lambda x: x["name_cn"].strip() if x["name_cn"].strip() else x["name_ja"].strip(),
    axis=1
)
anime["title_search_1"] = anime["name_ja"].fillna("").astype(str).str.strip()
anime["title_search_2"] = anime["name_cn"].fillna("").astype(str).str.strip()

anime = anime.drop_duplicates(subset=["anime_id"])

# 3. tag 表标准化
tag = tag.rename(columns={"id": "anime_id", "name": "name_ja"}).copy()
tag["tag"] = tag["tag"].fillna("").astype(str).str.strip()
tag = tag[tag["tag"] != ""]
tag = tag.drop_duplicates(subset=["anime_id", "tag"])

# 4. character 表标准化
char = char.rename(columns={"subject_id": "anime_id"}).copy()
char["anime"] = char["anime"].fillna("").astype(str).str.strip()
char["character"] = char["character"].fillna("").astype(str).str.strip()
char["name_cn"] = char["name_cn"].fillna("").astype(str).str.strip()
char["cv"] = char["cv"].fillna("").astype(str).str.strip()
char["relation"] = char["relation"].fillna("").astype(str).str.strip()

char = char[char["character"] != ""]
char = char.drop_duplicates(subset=["anime_id", "character", "cv", "relation"])

# 只保留主表里存在的 anime_id
valid_ids = set(anime["anime_id"])
char_orphan = char[~char["anime_id"].isin(valid_ids)].copy()
char = char[char["anime_id"].isin(valid_ids)].copy()

# 5. relation 表标准化
rel = rel.copy()
rel["target_name_cn"] = rel["target_name_cn"].fillna("").astype(str).str.strip()
rel["target_name"] = rel["target_name"].fillna("").astype(str).str.strip()
rel["relation_type"] = rel["relation_type"].fillna("").astype(str).str.strip()
rel["group"] = rel["group"].fillna("").astype(str).str.strip()

rel = rel.drop_duplicates(subset=["source_id", "target_id", "relation_type"])

# source 必须在主表里
rel = rel[rel["source_id"].isin(valid_ids)].copy()

# 6. 导出
# Canonical processed anime file. Keep anime_master.csv as a compatibility alias
# because older scripts and notes still reference it.
anime.to_csv(OUT / "anime_general_info_clean.csv", index=False, encoding="utf-8-sig")
anime.to_csv(OUT / "anime_master.csv", index=False, encoding="utf-8-sig")
tag.to_csv(OUT / "anime_tag_clean.csv", index=False, encoding="utf-8-sig")
char.to_csv(OUT / "anime_character_clean.csv", index=False, encoding="utf-8-sig")
rel.to_csv(OUT / "anime_relations_clean.csv", index=False, encoding="utf-8-sig")
char_orphan.to_csv(OUT / "anime_character_orphan.csv", index=False, encoding="utf-8-sig")

print("anime_general_info_clean:", anime.shape)
print("anime_master (alias):", anime.shape)
print("anime_tag_clean:", tag.shape)
print("anime_character_clean:", char.shape)
print("anime_relations_clean:", rel.shape)
print("character_orphan:", char_orphan.shape)

print("\nSample anime_general_info_clean:")
print(anime.head(2).to_string())
