import json
from pathlib import Path

ROOT = Path("/Users/wangyouqi/Documents/DesktopOrganizer/Web Development/Yoji_Anime")
DATA_DIR = ROOT / "data" / "processed"
IN_FILE = DATA_DIR / "anime_docs_with_style.jsonl"
OUT_FILE = DATA_DIR / "anime_chunks_with_style.jsonl"


def compact_list(values, limit=10, drop_values=None):
    drop_values = set(drop_values or [])
    result = []
    seen = set()
    for v in values or []:
        if v is None:
            continue
        s = str(v).strip()
        if not s or s in seen or s in drop_values:
            continue
        seen.add(s)
        result.append(s)
        if len(result) >= limit:
            break
    return result


def make_chunk(doc, section, text):
    meta = doc.get("metadata", {}) or {}
    style = doc.get("style", {}) or {}

    chunk = {
        "chunk_id": f"{doc['doc_id']}_{section}",
        "doc_id": doc["doc_id"],
        "entity_type": doc["entity_type"],
        "entity_id": doc["entity_id"],
        "title": doc["title"],
        "section": section,
        "text": text.strip(),
        "metadata": {
            "title_ja": doc.get("title_ja", ""),
            "title_cn": doc.get("title_cn", ""),
            "date": meta.get("date", ""),
            "country": meta.get("country", ""),
            "platform": meta.get("platform", ""),
            "score": meta.get("score"),
            "rank": meta.get("rank"),
            "episodes": meta.get("episodes"),
            "studio": meta.get("studio", ""),
            "director": meta.get("director", ""),
            "tags": compact_list(meta.get("tags", []), limit=12, drop_values={"TV"}),
            "characters": compact_list(meta.get("characters", []), limit=10),
            "voice_actors": compact_list(meta.get("voice_actors", []), limit=10),
            "related_works": compact_list(meta.get("related_works", []), limit=10),
            # style fields (empty string if not a seed entry)
            "mood": style.get("mood", ""),
            "themes": style.get("themes", ""),
            "tone": style.get("tone", ""),
            "pace": style.get("pace", ""),
            "audience": style.get("audience", ""),
        }
    }
    return chunk


chunks_written = 0
style_chunks_written = 0

with open(IN_FILE, "r", encoding="utf-8") as fin, open(OUT_FILE, "w", encoding="utf-8") as fout:
    for line in fin:
        line = line.strip()
        if not line:
            continue

        doc = json.loads(line)
        meta = doc.get("metadata", {}) or {}
        style = doc.get("style", {}) or {}

        title = doc.get("title", "").strip()
        title_ja = doc.get("title_ja", "").strip()
        title_cn = doc.get("title_cn", "").strip()

        date = str(meta.get("date", "")).strip()
        country = str(meta.get("country", "")).strip()
        platform = str(meta.get("platform", "")).strip()
        studio = str(meta.get("studio", "")).strip()
        director = str(meta.get("director", "")).strip()

        score = meta.get("score")
        rank = meta.get("rank")
        episodes = meta.get("episodes")

        tags = compact_list(meta.get("tags", []), limit=12, drop_values={"TV"})
        characters = compact_list(meta.get("characters", []), limit=10)
        voice_actors = compact_list(meta.get("voice_actors", []), limit=10)
        related_works = compact_list(meta.get("related_works", []), limit=10)

        full_text = doc.get("text", "")

        parts = [p.strip() for p in full_text.split("\n") if p.strip()]
        part_map = {}

        for p in parts:
            if p.startswith("作品名："):
                part_map["overview"] = p
            elif p.startswith("剧情简介："):
                part_map["summary"] = p
            elif p.startswith("标签："):
                part_map["tags"] = p
            elif p.startswith("主要角色："):
                part_map["characters"] = p
            elif p.startswith("相关声优："):
                part_map["voice_actors"] = p
            elif p.startswith("关联作品："):
                part_map["related_works"] = p
            elif p.startswith("风格描述："):
                part_map["style_profile"] = p

        overview_text = part_map.get("overview")
        if not overview_text:
            bits = [f"作品名：{title}。"]
            if title_ja and title_ja != title:
                bits.append(f"日文名：{title_ja}。")
            if title_cn and title_cn != title:
                bits.append(f"中文名：{title_cn}。")
            if country:
                bits.append(f"国家/地区：{country}。")
            if platform:
                bits.append(f"播出形式：{platform}。")
            if date:
                bits.append(f"首播时间：{date}。")
            if episodes not in [None, ""]:
                bits.append(f"集数：{episodes}。")
            if studio:
                bits.append(f"制作公司：{studio}。")
            if director:
                bits.append(f"导演：{director}。")
            if score not in [None, ""]:
                bits.append(f"评分：{score}。")
            if rank not in [None, ""]:
                bits.append(f"排名：{rank}。")
            overview_text = " ".join(bits)

        chunk_candidates = [
            ("overview", overview_text),
            ("summary", part_map.get("summary", "")),
            ("tags", part_map.get("tags", "")),
            ("characters", part_map.get("characters", "")),
            ("voice_actors", part_map.get("voice_actors", "")),
            ("related_works", part_map.get("related_works", "")),
            ("style_profile", part_map.get("style_profile", "")),
        ]

        for section, text in chunk_candidates:
            if text and text.strip():
                chunk = make_chunk(doc, section, text)
                fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                chunks_written += 1
                if section == "style_profile":
                    style_chunks_written += 1

print(f"anime_chunks_with_style written: {chunks_written}")
print(f"style_profile chunks: {style_chunks_written}")
print(f"Output: {OUT_FILE}")
