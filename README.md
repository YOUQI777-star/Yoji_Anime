# YOJI Anime

YOJI is an anime exploration platform built around a Neo4j knowledge graph, a Flask API layer, and a static frontend for graph navigation, search, AI-assisted Q&A, and lightweight user profiles.

Live: [yoji-anime.vercel.app](https://yoji-anime.vercel.app)

---

## Architecture

```
Frontend (static HTML / CSS / JS — Vercel)
    ↓
Flask API (Google Cloud Run)
    ├── Neo4j AuraDB         — knowledge graph
    ├── PostgreSQL           — users / sessions / favorites
    ├── ChromaDB (local)     — vector store for hybrid RAG
    ├── OpenAI               — embeddings + streaming answers
    ├── Bangumi API          — cover images
    └── trace.moe            — screenshot identification
```

---

## Knowledge Graph

The Neo4j graph currently contains:

| Node type    | Count  |
|-------------|--------|
| Anime       | 10,774 |
| Character   | 81,309 |
| VoiceActor  | 6,454  |
| Studio      | 1,293  |
| Tag         | 47     |

| Relationship   | Count  |
|---------------|--------|
| HAS_CHARACTER | 81,309 |
| VOICED_BY     | 78,438 |
| RELATED_TO    | 18,217 |

Key relationship types:

- `HAS_CHARACTER` — Anime → Character
- `VOICED_BY` — Character → VoiceActor
- `HAS_TAG` — Anime → Tag
- `PRODUCED_BY` — Anime → Studio
- `ORIGIN_COUNTRY` — Anime → Country
- `RELATED_TO` — Anime → Anime, with `group` (main / extra / skip / alt / universe) and `relation_type` (続編 / 前篇 / 总集篇 etc.)

Data sources:

- Original CSV-based import via `scripts/graph/import_neo4j.py`
- Bangumi Archive supplement via `scripts/graph/import_new_anime.py` — adds 932 high-quality anime (rank < 3000, score > 0) with characters, voice actors, studios, tags, and country detection
- Backfill of missing summary / score / rank / name_cn via `scripts/graph/fill_missing_data.py`
- Series relation edges from Bangumi Archive via `scripts/graph/build_archive_relation_increment.py` + `merge_archive_relation_increment.py`

---

## RAG Pipeline

Hybrid retrieval uses:

- **Neo4j** for structured graph context (characters, studios, tags, relations)
- **ChromaDB** for vector similarity over anime summaries and style chunks
- **OpenAI** `text-embedding-3-small` for embedding, `gpt-4o` for generation

RAG corpus stats:

| Artifact                          | Count  |
|----------------------------------|--------|
| `data/processed/anime_docs.jsonl` | 10,774 |
| `data/processed/anime_chunks.jsonl` | 43,700 |
| ChromaDB `anime_chunks` collection | 43,700 |

Recommendation retrieval uses summary-based vector similarity (`_vec_similar_by_summary`): embeds the source anime's stored summary, then queries ChromaDB with `where={"section": "summary"}` to find thematically similar anime — more semantically precise than tag overlap.

---

## Features

### Graph exploration

- Search anime, characters, voice actors, tags, and studios
- Expand any node to reveal its neighbors in the graph
- Switch display language between Chinese and Japanese names
- Tap a node to open a detail panel with metadata, cover art, and related info
- Save favorites (requires login)

### Recommendations

- Enter an anime title → get up to 10 similar anime ranked by shared tags, voice actors, studios, and summary similarity
- Knowledge graph shows: source node + recommended anime + up to 5 main characters per recommendation + shared tags as connectors

### Series classification

- For any anime, view its related works grouped by relationship type (続編, 前篇, 総集篇 etc.)
- Grouped into: main series, extras, compilations / theatrical edits, alternate versions, universe works
- Not a watch-order recommendation — a neutral classification of what exists

### AI assistant (Yoji)

- `/ask` — streaming graph-grounded Q&A. Yoji identifies intent, retrieves relevant graph context, and answers with personality
- `/rag/ask` — hybrid RAG: graph context + vector chunks + OpenAI generation
- Recognizes logged-in users by display name
- Gracefully degrades if OpenAI key is missing

### Other

- Autocomplete search
- Tag-based discovery (`/tags`, `/anime_by_tag`)
- Casting lookup — find anime that share voice actors
- Niche finder — filter by popularity and richness
- Cover art via Bangumi
- Screenshot identification via trace.moe
- User accounts, sessions, and favorites (PostgreSQL)

---

## Backend API

Flask app at [`backend/app.py`](./backend/app.py). Deployed to Google Cloud Run.

### Endpoints

| Group | Endpoints |
|---|---|
| Health | `GET /`, `GET /health`, `GET /db-health` |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Favorites | `GET /favorites`, `POST /favorites`, `DELETE /favorites/<id>` |
| Graph | `GET /search`, `GET /autocomplete`, `GET /expand`, `GET /anime`, `GET /character`, `GET /studio`, `GET /relations` |
| Discovery | `GET /tags`, `GET /anime_by_tag`, `GET /recommend`, `GET /casting`, `GET /niche`, `GET /watch_order` |
| Media | `GET /cover`, `POST /identify` |
| AI | `POST /ask` |
| RAG | `GET /rag/health`, `POST /rag/ask`, `POST /rag/recommend` |

---

## Repository Structure

```
Yoji_Anime/
├── backend/
│   ├── app.py                     # main Flask API
│   ├── rag_routes.py              # RAG blueprint
│   ├── neo4j_client.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── test_connection.py
├── frontend/
│   ├── public/
│   │   ├── index.html             # landing page
│   │   ├── graph.html             # graph explorer
│   │   ├── profile.html           # user profile
│   │   ├── app.js                 # auth + API utilities
│   │   ├── graph.js               # graph interaction logic
│   │   ├── config.js              # API base URL
│   │   ├── style.css
│   │   └── yoji.png               # Yoji avatar
│   └── vercel.json
├── scripts/
│   ├── graph/
│   │   ├── import_neo4j.py                      # initial graph import
│   │   ├── import_new_anime.py                  # Bangumi Archive supplement (932 anime)
│   │   ├── fill_missing_data.py                 # backfill summary/score/rank/name_cn
│   │   ├── build_archive_relation_increment.py  # series relation edges from Archive
│   │   ├── merge_archive_relation_increment.py  # merge relation edges into Neo4j
│   │   ├── normalize_related_to_edges.py        # normalize relation edge properties
│   │   ├── export_graph_snapshot.py             # export Neo4j → CSV
│   │   └── test_graph_queries.py
│   ├── rag/
│   │   ├── build_canonical_tables.py
│   │   ├── build_anime_docs.py
│   │   ├── build_anime_chunks.py
│   │   ├── build_anime_chunks_with_style.py
│   │   ├── build_chroma_index.py                # full Chroma rebuild
│   │   ├── build_chroma_style_seed.py
│   │   ├── resume_chroma_index.py               # checkpoint-resume for interrupted builds
│   │   ├── update_rag_incremental.py            # incremental RAG sync (Neo4j → Chroma)
│   │   ├── check_rag_sync.py                    # validate Neo4j / JSONL / Chroma alignment
│   │   ├── merge_style_seed.py
│   │   ├── intent.py
│   │   ├── retriever.py
│   │   ├── generator.py
│   │   └── ask.py
│   └── data_cleaning.py
├── data/
│   ├── READY_VERSION/             # source CSVs
│   ├── processed/                 # canonical tables + RAG artifacts
│   └── chroma_db/                 # ChromaDB vector store (local only)
└── README.md
```

---

## Environment Variables

```bash
# Neo4j (required — app will not start without these)
NEO4J_URI=
NEO4J_USER=
NEO4J_PASSWORD=
NEO4J_DATABASE=neo4j

# PostgreSQL (required for auth / favorites)
DATABASE_URL=

# OpenAI (required for /ask and RAG pipeline)
OPENAI_API_KEY=

# Bangumi (optional — improves cover quality)
BANGUMI_TOKEN=

# Server
PORT=8080

# RAG paths (used by rag_routes.py and scripts)
PROJECT_ROOT=
CHROMA_DIR=
```

---

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# create .env with the variables above
python app.py
```

Runs on `http://localhost:8080` by default.

### Frontend

Static files — open directly or serve locally:

```bash
cd frontend
npx serve public
```

Point `frontend/public/config.js` at your local Flask server for local development.

---

## Data Pipeline

### Initial import

```bash
# 1. Build canonical tables from source CSVs
python scripts/rag/build_canonical_tables.py

# 2. Import graph into Neo4j
python scripts/graph/import_neo4j.py

# 3. Import Bangumi Archive supplement (932 anime)
python scripts/graph/import_new_anime.py

# 4. Backfill missing metadata
python scripts/graph/fill_missing_data.py

# 5. Build and merge series relation edges
python scripts/graph/build_archive_relation_increment.py
python scripts/graph/merge_archive_relation_increment.py
```

### RAG corpus

```bash
# Build docs and chunks
python scripts/rag/build_anime_docs.py
python scripts/rag/build_anime_chunks.py

# Build Chroma index (from scratch)
python scripts/rag/build_chroma_index.py

# If the build was interrupted, resume without re-embedding existing chunks
python scripts/rag/resume_chroma_index.py
```

### Incremental sync

When Neo4j has newer anime than the RAG artifacts, run the incremental updater instead of rebuilding:

```bash
# Dry run — report what would change
python scripts/rag/update_rag_incremental.py --dry-run

# Full resumable sync
python scripts/rag/update_rag_incremental.py
```

Flags:

- `--dry-run` — count-only, no writes
- `--limit N` — process at most N missing anime
- `--batch-size N` — embedding batch size
- `--include-no-summary` — also process anime without summaries

### Validate sync

```bash
python scripts/rag/check_rag_sync.py

# Full Chroma chunk-ID existence check (slow)
python scripts/rag/check_rag_sync.py --deep-chroma-check
```

---

## Deployment

| Layer | Platform |
|---|---|
| Frontend | Vercel |
| Backend API | Google Cloud Run (`asia-southeast1`) |
| Graph DB | Neo4j AuraDB |
| User DB | PostgreSQL |
| Vector store | ChromaDB (mounted in container) |

Backend deploy:

```bash
cd backend
gcloud builds submit --tag gcr.io/<project>/anime-kg-api
gcloud run deploy anime-kg-api \
  --image gcr.io/<project>/anime-kg-api \
  --platform managed \
  --region asia-southeast1
```

---

## Recent Changes

### Recommendation knowledge graph redesign

The `/recommend` knowledge graph previously showed all neighbors of the source anime, resulting in hundreds of nodes. It now shows:

- Source anime (center)
- Recommended anime nodes
- Up to 5 main characters per recommended anime
- Up to 3 shared tags per pair as connectors

Typical result: ~30 nodes vs the previous ~130+.

### Series classification (formerly watch order)

The watch order panel was renamed and restructured to "series classification" — it shows related works grouped by relationship type without implying a recommended viewing sequence.

Compilations and theatrical edits (総集篇 / 剧场版) are now shown as a separate group using Bangumi Archive `grp=skip` entries.

### Bangumi Archive data import

Added 932 high-quality anime from the Bangumi Archive (rank < 3000, score > 0, type = TV, non-NSFW) not previously in the graph, along with:

- 11,175 characters
- 9,935 VOICED_BY relationships
- Country detection from infobox text (handles cases where the name contains no kana)

### RAG summary-based recommendation

Replaced tag-overlap recommendation with summary vector similarity: the source anime's summary is embedded and used to query ChromaDB for semantically similar anime, which produces more thematically relevant recommendations than shared-tag counting.

### ChromaDB rebuild

After a HNSW compactor corruption error, the Chroma index was deleted and rebuilt clean. The final collection contains 43,700 chunks across 10,774 anime.

### Yoji avatar

Replaced the Yoji avatar with a clean background-removed version using chroma-key with spill suppression.
