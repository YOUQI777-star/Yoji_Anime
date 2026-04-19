# YOJI Anime

YOJI Anime is an anime exploration platform built around a Neo4j knowledge graph, a Flask API layer, and a static frontend for graph navigation, search, AI-assisted Q&A, and lightweight user profiles.

The repository has moved well beyond the original scaffold stage. It now includes:

- a browser-based graph exploration UI built with Cytoscape.js
- account registration, login, session management, and favorites
- anime search, autocomplete, tag-based discovery, casting lookups, and watch-order helpers
- cover lookup through Bangumi
- screenshot identification through `trace.moe`
- two AI paths:
  - `/ask` for direct graph-grounded streaming Q&A
  - `/rag/*` for hybrid RAG using Neo4j + Chroma + OpenAI
- local data preparation scripts for canonical tables, graph import, and RAG corpus generation

## Architecture

```text
Frontend (static HTML / CSS / JS)
    -> talks to Flask API
Flask API
    -> Neo4j AuraDB for graph queries
    -> PostgreSQL for users / sessions / favorites
    -> OpenAI for AI answers and embeddings
    -> Bangumi for cover images
    -> trace.moe for screenshot identification
ChromaDB
    -> local vector store for hybrid RAG retrieval
```

## Core Product Areas

### 1. Landing and graph experience

The frontend under [`frontend/public`](./frontend/public) is no longer a placeholder. It includes:

- a styled landing page in [`frontend/public/index.html`](./frontend/public/index.html)
- a graph exploration page in [`frontend/public/graph.html`](./frontend/public/graph.html)
- a profile page in [`frontend/public/profile.html`](./frontend/public/profile.html)
- shared auth and API utilities in [`frontend/public/app.js`](./frontend/public/app.js)
- graph interaction logic in [`frontend/public/graph.js`](./frontend/public/graph.js)

From the graph page, users can:

- search anime, characters, voice actors, tags, and studios
- expand nodes in the graph
- switch graph label language between Chinese and original names
- open detail panels for anime metadata
- save favorites after logging in
- ask AI questions with the current graph context
- request watch-order suggestions for connected works

### 2. Backend API

The Flask API lives in [`backend/app.py`](./backend/app.py) and currently exposes endpoints for:

- health checks: `/`, `/health`, `/db-health`
- auth: `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`
- favorites: `/favorites`, `/favorites/<id>`
- graph data: `/search`, `/autocomplete`, `/expand`, `/anime`, `/character`, `/studio`, `/relations`
- discovery: `/tags`, `/recommend`, `/casting`, `/niche`, `/anime_by_tag`, `/watch_order`
- media helpers: `/cover`, `/identify`
- AI: `/ask`

The hybrid RAG blueprint in [`backend/rag_routes.py`](./backend/rag_routes.py) adds:

- `GET /rag/health`
- `POST /rag/ask`
- `POST /rag/recommend`

### 3. User accounts and persistence

The backend initializes PostgreSQL tables for:

- `users`
- `user_sessions`
- `favorites`

That means the project is no longer just a read-only data demo. It now supports persistent user state and a profile/favorites flow.

### 4. Knowledge graph and RAG pipeline

The data pipeline now has a clearer staged flow:

1. Raw source CSVs live in [`data/READY_VERSION`](./data/READY_VERSION)
2. Canonical cleaned tables are generated into [`data/processed`](./data/processed)
3. Neo4j import scripts build the graph
4. RAG scripts generate document and chunk corpora
5. Chroma indexes are built for retrieval

Main pipeline scripts include:

- [`scripts/graph/export_graph_snapshot.py`](./scripts/graph/export_graph_snapshot.py)
- [`scripts/rag/build_canonical_tables.py`](./scripts/rag/build_canonical_tables.py)
- [`scripts/graph/import_neo4j.py`](./scripts/graph/import_neo4j.py)
- [`scripts/rag/build_anime_docs.py`](./scripts/rag/build_anime_docs.py)
- [`scripts/rag/build_anime_chunks.py`](./scripts/rag/build_anime_chunks.py)
- [`scripts/rag/build_anime_chunks_with_style.py`](./scripts/rag/build_anime_chunks_with_style.py)
- [`scripts/rag/build_chroma_index.py`](./scripts/rag/build_chroma_index.py)
- [`scripts/rag/build_chroma_style_seed.py`](./scripts/rag/build_chroma_style_seed.py)
- [`scripts/rag/retriever.py`](./scripts/rag/retriever.py)
- [`scripts/rag/generator.py`](./scripts/rag/generator.py)

## Current Repository Structure

```text
Yoji_Anime/
├── backend/
│   ├── app.py
│   ├── rag_routes.py
│   ├── neo4j_client.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── test_connection.py
├── frontend/
│   ├── public/
│   │   ├── index.html
│   │   ├── graph.html
│   │   ├── profile.html
│   │   ├── app.js
│   │   ├── graph.js
│   │   ├── config.js
│   │   └── style.css
│   └── vercel.json
├── scripts/
│   ├── graph/
│   │   ├── import_neo4j.py
│   │   └── test_graph_queries.py
│   ├── rag/
│   │   ├── ask.py
│   │   ├── generator.py
│   │   ├── intent.py
│   │   ├── retriever.py
│   │   ├── build_*.py
│   │   └── test_retrieve_*.py
│   ├── data_cleaning.py
│   ├── crawl_series_relations.py
│   ├── fetch_character_cn_names.py
│   └── fix_rls.sql
├── data/
│   ├── READY_VERSION/
│   └── processed/
├── Dockerfile
├── Neo4j-2f775b9b-Created-2026-03-24.txt
└── README.md
```

## Data Model

From the import and query logic, the graph currently centers on these node types:

- `Anime`
- `Character`
- `VoiceActor`
- `Tag`
- `Studio`
- `Country`

Key relationship types used by the application include:

- `HAS_CHARACTER`
- `VOICED_BY`
- `HAS_TAG`
- `RELATED_TO`
- `PRODUCED_BY`
- `ORIGIN_COUNTRY`

## Environment Variables

The backend expects the following environment variables to be available:

```bash
NEO4J_URI=
NEO4J_USER=
NEO4J_PASSWORD=
NEO4J_DATABASE=neo4j

DATABASE_URL=

OPENAI_API_KEY=
BANGUMI_TOKEN=

PORT=8080
PROJECT_ROOT=
CHROMA_DIR=
```

Notes:

- `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` are required for the Flask app to boot.
- `DATABASE_URL` is required for auth, sessions, and favorites.
- `OPENAI_API_KEY` is required for `/ask` and the hybrid RAG pipeline.
- `BANGUMI_TOKEN` improves cover lookup quality but the API can still run without it.
- some scripts also fall back to the local credentials file [`Neo4j-2f775b9b-Created-2026-03-24.txt`](./Neo4j-2f775b9b-Created-2026-03-24.txt) during local development

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

By default the backend runs on `http://localhost:8080`.

### Frontend

The frontend is a static app. You can either open files directly or serve them locally.

```bash
cd frontend
npx serve public
```

The frontend reads its API base URL from [`frontend/public/config.js`](./frontend/public/config.js). For local development, point that file at your local Flask server if needed.

## RAG Workflow

The hybrid RAG implementation combines:

- intent classification
- graph retrieval from Neo4j
- vector retrieval from Chroma
- OpenAI generation for final answers

Relevant files:

- [`scripts/rag/intent.py`](./scripts/rag/intent.py)
- [`scripts/rag/retriever.py`](./scripts/rag/retriever.py)
- [`scripts/rag/generator.py`](./scripts/rag/generator.py)
- [`backend/rag_routes.py`](./backend/rag_routes.py)

The backend is designed to degrade gracefully in some cases:

- if Chroma is missing, retriever logic can fall back toward graph-only retrieval
- if RAG dependencies fail to initialize, the main Flask app can still start without the RAG blueprint
- if `/ask` does not have an OpenAI key, it returns an AI-not-configured fallback response

## Data Preparation Workflow

The naming convention for source and processed data files is documented in [`data/README.md`](./data/README.md).

A typical local pipeline looks like this:

```bash
# 1. Export the current complete graph snapshot back into READY_VERSION
python scripts/graph/export_graph_snapshot.py

# 2. Build cleaned canonical tables
python scripts/rag/build_canonical_tables.py

# 3. Import graph data into Neo4j
python scripts/graph/import_neo4j.py

# 4. Build RAG documents and chunks
python scripts/rag/build_anime_docs.py
python scripts/rag/build_anime_chunks.py

# 5. Build style-aware RAG artifacts
python scripts/rag/merge_style_seed.py
python scripts/rag/build_anime_chunks_with_style.py

# 6. Build Chroma indexes
python scripts/rag/build_chroma_index.py
python scripts/rag/build_chroma_style_seed.py

# 7. Validate data consistency
python scripts/check_data_integrity.py
```

## Incremental RAG Maintenance

When Neo4j has newer anime than the local RAG artifacts, you do not need to rebuild everything from scratch.

Use the incremental updater:

```bash
venv/bin/python scripts/rag/update_rag_incremental.py --dry-run
venv/bin/python scripts/rag/update_rag_incremental.py
```

What it updates:

- `data/processed/anime_docs.jsonl`
- `data/processed/anime_chunks.jsonl`
- Chroma collection `anime_chunks`

The updater is resumable:

- it only appends missing docs
- it only appends missing chunks
- it only embeds chunk IDs still missing from Chroma

To verify sync after a rebuild or incremental update:

```bash
venv/bin/python scripts/rag/check_rag_sync.py
```

That checker compares Neo4j, docs JSONL, chunks JSONL, and Chroma, then reports whether drift still exists.

For a slower full chunk-id existence check against Chroma:

```bash
venv/bin/python scripts/rag/check_rag_sync.py --deep-chroma-check
```

## Deployment Notes

The repository currently reflects a split deployment model:

- static frontend configured for Vercel
- Flask backend configured for container deployment
- Neo4j AuraDB as the hosted graph database
- PostgreSQL for user data

`frontend/public/config.js` is currently pointed at a deployed Cloud Run backend URL, which suggests the app has already moved beyond local-only development.

## Project Status

The old README described the project as mostly unfinished phases. That is no longer accurate.

Based on the code currently in this repository:

- graph exploration is implemented
- backend graph APIs are implemented
- auth and favorites are implemented
- profile UI is implemented
- AI Q&A is implemented
- hybrid RAG is implemented
- screenshot identification is implemented
- data cleaning and import scripts are implemented
- source and processed data layers are now synchronized from the current graph snapshot
- RAG JSONL artifacts are rebuilt from the synchronized processed layer

What still looks like active development:

- the graph frontend is being iterated on
- processed data artifacts and newer RAG scripts are still evolving
- deployment/config cleanup and documentation consistency still need work

---

## Recent Changes

### RAG Pipeline Improvements

**`scripts/rag/intent.py`**
- Added `r"想看.{0,20}(系|类型|风格)"` to `RECOMMEND_PATTERNS` to catch inputs like "想看治愈系" that don't end with "的番"
- Added explicit genre keyword patterns (治愈、日常、热血、悬疑 etc.) as direct recommend triggers, so users don't need to use specific sentence structures

**`scripts/rag/retriever.py`**
- Added `MIN_VEC_SCORE = 0.15` threshold — vector results with score below this are filtered out before being injected into the prompt. This prevents clearly irrelevant or negative-score chunks from reaching the LLM
- Replaced tag-overlap recommendation lookup with `_vec_similar_by_summary(title)`, which:
  - resolves the source anime from Neo4j
  - reads its stored `summary`
  - embeds that summary with `text-embedding-3-small`
  - queries Chroma `anime_chunks` with `where={"section": "summary"}`
  - filters out the source anime itself
  - returns `summary_similar` blocks instead of shared-tag blocks
- If the source anime has no summary or Chroma summary retrieval is unavailable, recommendation flow now falls back to the existing query-string vector retrieval path

**`backend/rag_routes.py`**
- When `intent == "opinion"` and `graph_context` is non-empty, the user message is now constructed as `"用户当前正在查看：{graph_context}，并对这部作品提出了以下问题"` instead of injecting context separately. This makes it clearer to the LLM that the question is specifically about the node the user is viewing.

**`backend/app.py`**
- `/autocomplete`: changed sort order from `ORDER BY a.rank ASC` to `ORDER BY CASE WHEN coalesce(a.rank, 0) > 0 THEN a.rank ELSE 99999 END ASC`. The `popularity` field does not exist on Anime nodes; rank is the correct proxy for sorting by relevance/popularity. Unranked nodes (rank=0 or null) are now pushed to the end.
- `/studio`: changed from exact match `{name: $name}` to `WHERE toLower(s.name) = toLower($name)` so studio filtering is case-insensitive (e.g. "bones" now returns the same results as "BONES")


---

## Recommended Next Documentation Improvements

If this README keeps evolving, the next high-value additions would be:

- a real `.env.example` for backend and scripts
- example requests for the main API routes
- a dedicated data dictionary for each CSV in `data/processed`
- deployment instructions for Vercel + Cloud Run + Postgres
- screenshots of the landing page, graph page, and profile page
