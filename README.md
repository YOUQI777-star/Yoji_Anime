# Anime Knowledge Graph

An intelligent anime exploration platform combining Neo4j knowledge graphs, RAG-based AI Q&A, and screenshot identification.

## Architecture

```
GitHub (code) → Vercel (frontend) + Cloud Run (backend API)
                                          ↕
                                    Neo4j AuraDB
```

| Layer | Technology | URL |
|-------|-----------|-----|
| Frontend | HTML/JS + Cytoscape.js → Vercel | `https://anime-kg.vercel.app` |
| Backend API | Python Flask → Cloud Run | `https://anime-kg-xxx.run.app` |
| Graph DB | Neo4j AuraDB Free | Hosted |
| Vector DB | ChromaDB (in-container) | In-process |

## Project Structure

```
anime-kg/
├── backend/          # Flask API (deployed to Cloud Run)
│   ├── app.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/         # Static site (deployed to Vercel)
│   ├── public/
│   │   └── index.html
│   └── vercel.json
├── scripts/          # Data pipeline scripts (run locally)
│   ├── import_to_neo4j.py
│   ├── build_chromadb.py
│   └── data_cleaning.py
├── data/             # Local CSVs (gitignored)
└── .github/
    └── workflows/
        └── deploy-backend.yml
```

## Quick Start

### Backend (local dev)
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
python app.py
```

### Frontend (local dev)
Open `frontend/public/index.html` directly in browser, or:
```bash
cd frontend
npx serve public
```

## Development Phases

- [x] Phase 0: Project scaffold
- [ ] Phase 1: AuraDB graph data upload
- [ ] Phase 2: Backend API (search / expand / recommend)
- [ ] Phase 3: Frontend graph interaction
- [ ] Phase 4: RAG + AI Q&A
- [ ] Phase 5: Cloud Run + Vercel deployment
- [ ] Phase 6: UI polish + cover images + chat UI
