import csv
import json
from pathlib import Path

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
SEED_FILE = DATA_DIR / "anime_style_seed.csv"
DOCS_IN = DATA_DIR / "anime_docs.jsonl"
DOCS_OUT = DATA_DIR / "anime_docs_with_style.jsonl"

# Load style seed indexed by anime_id
style_map = {}
with open(SEED_FILE, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        anime_id = int(row["anime_id"])
        style_map[anime_id] = {
            "mood": row["mood"],
            "themes": row["themes"],
            "tone": row["tone"],
            "pace": row["pace"],
            "audience": row["audience"],
            "style_profile": row["style_profile"],
        }

print(f"Style seed loaded: {len(style_map)} entries")
print("IDs:", sorted(style_map.keys()))

merged = 0
total = 0

with open(DOCS_IN, "r", encoding="utf-8") as fin, open(DOCS_OUT, "w", encoding="utf-8") as fout:
    for line in fin:
        line = line.strip()
        if not line:
            continue
        total += 1
        doc = json.loads(line)
        entity_id = int(doc["entity_id"])

        if entity_id in style_map:
            s = style_map[entity_id]
            doc["style"] = s
            # Append style text to the full text field
            style_text = f"\n风格描述：{s['style_profile']}"
            doc["text"] = doc["text"].rstrip() + style_text
            merged += 1

        fout.write(json.dumps(doc, ensure_ascii=False) + "\n")

print(f"Total docs: {total}")
print(f"Style merged: {merged}")
if merged < len(style_map):
    missing = set(style_map.keys()) - {int(json.loads(l)["entity_id"]) for l in open(DOCS_IN, encoding="utf-8") if l.strip()}
    print(f"WARNING: {len(style_map) - merged} seed IDs not found in docs: {missing}")
print(f"Output: {DOCS_OUT}")
