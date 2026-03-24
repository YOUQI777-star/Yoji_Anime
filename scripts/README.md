# Scripts

Data pipeline scripts — run locally, never deployed.

| Script | Purpose |
|--------|---------|
| `import_to_neo4j.py` | Import CSV → AuraDB (Phase 1) |
| `build_chromadb.py`  | Build ChromaDB vector index from Neo4j (Phase 4) |
| `data_cleaning.py`   | Clean and standardise raw CSV data |

## Usage

```bash
# Activate local venv first
source ../venv/bin/activate

# Import anime data
python import_to_neo4j.py --file ../data/anime_info_merged.csv --type anime

# Import relations
python import_to_neo4j.py --file ../data/anime_relations_fixed.csv --type relation

# Build vector index
python build_chromadb.py
```
