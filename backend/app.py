"""
Anime Knowledge Graph — Flask Backend
Deployed to Google Cloud Run.

Endpoints:
  GET  /health
  GET  /search        ?query=<str>
  GET  /expand        ?id=<raw_id>&type=<node_type>&limit=<int>
  GET  /recommend     ?id=<int>|name=<str>
  GET  /autocomplete  ?q=<str>
  GET  /relations     ?id=<int>&group=<str>
  GET  /cover         ?id=<int>
  GET  /casting       ?tags=<csv>
  GET  /character     ?name=<str>
  GET  /studio        ?name=<str>
  GET  /niche         ?pop=<int>&rich=<int>
  POST /ask           {question, anime_id?}
  POST /identify      multipart image
"""

import os
import time
import json

import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from neo4j import GraphDatabase

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Config from environment ───────────────────────────────────────
NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USER     = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
BANGUMI_TOKEN  = os.environ.get("BANGUMI_TOKEN", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ── Constants ─────────────────────────────────────────────────────
EXPAND_LIMIT     = 30
COVER_TTL        = 3600          # seconds
EXPANDABLE_TYPES = {"Anime", "Character", "VoiceActor", "Tag", "Studio"}

_cover_cache: dict = {}          # {anime_id: {"url": str|None, "ts": float}}


# ═══════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════

def _node_id(n) -> str:
    """Stable unique element id:  Label:raw_db_id"""
    label = list(n.labels)[0] if n.labels else "Unknown"
    raw   = str(n.get("id")) if "id" in n else str(n.element_id)
    return f"{label}:{raw}"


def _node_data(n) -> dict:
    label = list(n.labels)[0] if n.labels else "Unknown"
    data  = {
        "id":     _node_id(n),
        "raw_id": str(n.get("id") or n.element_id),
        "label":  n.get("name_cn") or n.get("name") or "Unknown",
        "type":   label,
    }
    for key in ("score", "rank", "date", "episodes", "country",
                "platform", "studio", "director", "summary", "name", "name_cn"):
        val = n.get(key)
        if val is not None:
            data[key] = val
    return data


def build_graph(cypher: str, params: dict) -> dict:
    """Run a Cypher query and return {nodes, edges} for Cytoscape.js."""
    nodes: dict = {}
    edges: list = []
    seen_edges: set = set()

    with driver.session() as session:
        for record in session.run(cypher, **params):
            for v in record.values():
                if v is None:
                    continue
                # Node
                if hasattr(v, "labels"):
                    nid = _node_id(v)
                    if nid not in nodes:
                        nodes[nid] = {"data": _node_data(v)}
                # Relationship
                elif hasattr(v, "type") and hasattr(v, "start_node") and hasattr(v, "end_node"):
                    src = _node_id(v.start_node)
                    tgt = _node_id(v.end_node)
                    for nd, node in ((src, v.start_node), (tgt, v.end_node)):
                        if nd not in nodes:
                            nodes[nd] = {"data": _node_data(node)}
                    eid = f"{src}-{v.type}-{tgt}"
                    if eid not in seen_edges:
                        seen_edges.add(eid)
                        rel_data = {"id": eid, "source": src,
                                    "target": tgt, "label": v.type}
                        for prop in ("relation_type", "same_series", "group"):
                            val = v.get(prop)
                            if val is not None:
                                rel_data[prop] = val
                        edges.append({"data": rel_data})

    return {"nodes": list(nodes.values()), "edges": edges}


# ═══════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
def home():
    return jsonify({"service": "anime-kg-api", "status": "ok"})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


# ── /search ──────────────────────────────────────────────────────
@app.get("/search")
def search():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"nodes": [], "edges": [], "error": "empty query"}), 400

    if query.isdigit():
        cypher = """
        MATCH (a:Anime {id: $id})
        OPTIONAL MATCH (a)-[r]-(n)
        RETURN a, r, n LIMIT 200
        """
        return jsonify(build_graph(cypher, {"id": int(query)}))

    cypher = """
    CALL {
        MATCH (a:Anime)
        WHERE a.name CONTAINS $q OR a.name_cn CONTAINS $q
        RETURN a AS n
        UNION ALL
        MATCH (c:Character)
        WHERE c.name CONTAINS $q OR c.name_cn CONTAINS $q
        RETURN c AS n
        UNION ALL
        MATCH (v:VoiceActor)
        WHERE v.name CONTAINS $q OR v.name_cn CONTAINS $q
        RETURN v AS n
    }
    WITH DISTINCT n
    OPTIONAL MATCH (n)-[r]-(m)
    RETURN n, r, m LIMIT 200
    """
    return jsonify(build_graph(cypher, {"q": query}))


# ── /expand ──────────────────────────────────────────────────────
@app.get("/expand")
def expand():
    """Progressive graph traversal — 1-hop expansion of a selected node."""
    raw_id    = request.args.get("id",    "").strip()
    node_type = request.args.get("type",  "").strip()
    limit     = request.args.get("limit", EXPAND_LIMIT, type=int)

    if not raw_id or not node_type:
        return jsonify({"nodes": [], "edges": [], "error": "missing id or type"}), 400
    if node_type not in EXPANDABLE_TYPES:
        return jsonify({"nodes": [], "edges": [],
                        "error": f"unsupported type: {node_type}"}), 400

    try:    db_id = int(raw_id)
    except: db_id = raw_id          # Tag / Studio use name as id

    queries = {
        "Anime": """
            MATCH (a:Anime {id: $id})
            OPTIONAL MATCH (a)-[r1:HAS_CHARACTER]->(c:Character)
            OPTIONAL MATCH (a)-[r2:HAS_TAG]->(t:Tag)
            OPTIONAL MATCH (a)-[r3:PRODUCED_BY]->(s:Studio)
            OPTIONAL MATCH (a)-[r4:RELATED_TO]->(b:Anime)
            RETURN a, r1, c, r2, t, r3, s, r4, b LIMIT $limit
        """,
        "Character": """
            MATCH (c:Character {id: $id})
            OPTIONAL MATCH (c)-[r1:VOICED_BY]->(v:VoiceActor)
            OPTIONAL MATCH (a:Anime)-[r2:HAS_CHARACTER]->(c)
            RETURN c, r1, v, r2, a LIMIT $limit
        """,
        "VoiceActor": """
            MATCH (v:VoiceActor {id: $id})
            OPTIONAL MATCH (c:Character)-[r1:VOICED_BY]->(v)
            OPTIONAL MATCH (a:Anime)-[r2:HAS_CHARACTER]->(c)
            RETURN v, r1, c, r2, a LIMIT $limit
        """,
        "Tag": """
            MATCH (t:Tag {name: $id})
            OPTIONAL MATCH (a:Anime)-[r:HAS_TAG]->(t)
            RETURN t, r, a LIMIT $limit
        """,
        "Studio": """
            MATCH (s:Studio {name: $id})
            OPTIONAL MATCH (a:Anime)-[r:PRODUCED_BY]->(s)
            RETURN s, r, a LIMIT $limit
        """,
    }

    result = build_graph(queries[node_type], {"id": db_id, "limit": limit})
    result["truncated"] = (len(result["nodes"]) >= limit)
    return jsonify(result)


# ── /recommend ───────────────────────────────────────────────────
@app.get("/recommend")
def recommend():
    anime_id   = request.args.get("id",   type=int)
    anime_name = request.args.get("name", "").strip()

    if not anime_id and anime_name:
        with driver.session() as session:
            rec = session.run(
                "MATCH (a:Anime) WHERE a.name CONTAINS $q OR a.name_cn CONTAINS $q "
                "RETURN a.id AS id LIMIT 1", q=anime_name
            ).single()
            if rec:
                anime_id = rec["id"]

    if not anime_id:
        return jsonify({"nodes": [], "edges": []}), 400

    cypher = """
    MATCH (target:Anime {id: $id})
    OPTIONAL MATCH (target)-[:HAS_TAG]->(t:Tag)<-[:HAS_TAG]-(rec:Anime)
    WITH target, rec, count(DISTINCT t) AS tagScore
    WHERE rec IS NOT NULL AND rec.id <> $id
    OPTIONAL MATCH (target)-[:HAS_CHARACTER]->(:Character)-[:VOICED_BY]->(va:VoiceActor)
               <-[:VOICED_BY]-(:Character)<-[:HAS_CHARACTER]-(rec)
    WITH target, rec, tagScore, count(DISTINCT va) AS vaScore
    OPTIONAL MATCH (target)-[:PRODUCED_BY]->(st:Studio)<-[:PRODUCED_BY]-(rec)
    WITH target, rec, tagScore * 2 + vaScore * 3 + count(DISTINCT st) AS score
    ORDER BY score DESC LIMIT 10
    OPTIONAL MATCH (target)-[r1]-(x)
    OPTIONAL MATCH (rec)-[r2]-(y)
    RETURN target, rec, r1, x, r2, y LIMIT 300
    """
    return jsonify(build_graph(cypher, {"id": anime_id}))


# ── /autocomplete ─────────────────────────────────────────────────
@app.get("/autocomplete")
def autocomplete():
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    with driver.session() as session:
        rows = session.run(
            "MATCH (a:Anime) WHERE a.name CONTAINS $q OR a.name_cn CONTAINS $q "
            "RETURN a.id AS id, a.name AS name, a.name_cn AS name_cn LIMIT 10", q=q
        )
        return jsonify([{
            "id": r["id"], "name": r["name"] or "",
            "name_cn": r["name_cn"] or "",
            "display": r["name_cn"] or r["name"] or ""
        } for r in rows])


# ── /relations ────────────────────────────────────────────────────
@app.get("/relations")
def relations():
    anime_id = request.args.get("id", type=int)
    group    = request.args.get("group", "").strip()
    if not anime_id:
        return jsonify({"nodes": [], "edges": []}), 400

    if group:
        cypher = """
        MATCH (a:Anime {id: $id})-[r:RELATED_TO]->(b:Anime)
        WHERE r.group = $group
        RETURN a, r, b ORDER BY r.same_series DESC, r.relation_type LIMIT 50
        """
        return jsonify(build_graph(cypher, {"id": anime_id, "group": group}))

    cypher = """
    MATCH (a:Anime {id: $id})-[r:RELATED_TO]->(b:Anime)
    RETURN a, r, b ORDER BY r.same_series DESC, r.relation_type LIMIT 50
    """
    return jsonify(build_graph(cypher, {"id": anime_id}))


# ── /cover ────────────────────────────────────────────────────────
@app.get("/cover")
def cover():
    anime_id = request.args.get("id", type=int)
    if not anime_id:
        return jsonify({"image_url": None}), 400

    cached = _cover_cache.get(anime_id)
    if cached and time.time() - cached["ts"] < COVER_TTL:
        return jsonify({"image_url": cached["url"], "source": "cache"})

    try:
        resp = requests.get(
            f"https://api.bgm.tv/v0/subjects/{anime_id}",
            headers={"Authorization": f"Bearer {BANGUMI_TOKEN}",
                     "User-Agent": "anime-kg/1.0"},
            timeout=5
        )
        if resp.ok:
            images = resp.json().get("images", {})
            url = images.get("large") or images.get("medium") or images.get("small")
            _cover_cache[anime_id] = {"url": url, "ts": time.time()}
            return jsonify({"image_url": url, "source": "bangumi"})
    except Exception:
        pass

    _cover_cache[anime_id] = {"url": None, "ts": time.time()}
    return jsonify({"image_url": None})


# ── /casting ──────────────────────────────────────────────────────
@app.get("/casting")
def casting():
    tags     = request.args.get("tags", "").strip()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if not tag_list:
        return jsonify({"nodes": [], "edges": []}), 400
    cypher = """
    MATCH (va:VoiceActor)<-[:VOICED_BY]-(:Character)<-[:HAS_CHARACTER]-(a:Anime)-[:HAS_TAG]->(t:Tag)
    WHERE t.name IN $tags
    WITH va, count(DISTINCT a) AS score ORDER BY score DESC LIMIT 20
    MATCH (va)<-[r:VOICED_BY]-(c:Character)
    RETURN va, r, c LIMIT 200
    """
    return jsonify(build_graph(cypher, {"tags": tag_list}))


# ── /character ────────────────────────────────────────────────────
@app.get("/character")
def character_discovery():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"nodes": [], "edges": []}), 400
    cypher = """
    MATCH (c:Character) WHERE c.name = $name OR c.name_cn = $name
    MATCH (c)<-[:HAS_CHARACTER]-(a:Anime)
    MATCH (c)-[:VOICED_BY]->(va:VoiceActor)<-[:VOICED_BY]-(other:Character)
    MATCH (other)<-[:HAS_CHARACTER]-(rec:Anime)-[:HAS_TAG]->(tag:Tag)
    MATCH (a)-[:HAS_TAG]->(tag)
    WHERE other <> c
    RETURN c, a, va, other, rec, tag LIMIT 200
    """
    return jsonify(build_graph(cypher, {"name": name}))


# ── /studio ───────────────────────────────────────────────────────
@app.get("/studio")
def studio_style():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"nodes": [], "edges": []}), 400
    cypher = """
    MATCH (s:Studio {name: $name})<-[:PRODUCED_BY]-(a:Anime)-[:HAS_TAG]->(t:Tag)
    RETURN s, a, t LIMIT 200
    """
    return jsonify(build_graph(cypher, {"name": name}))


# ── /niche ────────────────────────────────────────────────────────
@app.get("/niche")
def niche():
    min_rank = request.args.get("pop",  500, type=int)
    min_tags = request.args.get("rich", 5,   type=int)
    cypher = """
    MATCH (a:Anime)-[r:HAS_TAG]->(t:Tag)
    WITH a, count(t) AS richness
    WHERE richness >= $min_tags AND a.rank >= $min_rank
    MATCH (a)-[r2:HAS_TAG]->(t2:Tag)
    RETURN a, r2, t2 LIMIT 200
    """
    return jsonify(build_graph(cypher, {"min_rank": min_rank, "min_tags": min_tags}))


# ── /ask ──────────────────────────────────────────────────────────
@app.post("/ask")
def ask():
    """GraphRAG AI Q&A with streaming SSE response."""
    body     = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    anime_id = body.get("anime_id")

    if not question:
        return jsonify({"error": "missing question"}), 400
    if not OPENAI_API_KEY:
        return jsonify({"error": "AI not configured", "fallback": True}), 503

    # Build graph context from Neo4j
    graph_context = ""
    if anime_id:
        try:
            with driver.session() as session:
                rec = session.run("""
                    MATCH (a:Anime {id: $id})
                    OPTIONAL MATCH (a)-[:HAS_TAG]->(t:Tag)
                    OPTIONAL MATCH (a)-[:HAS_CHARACTER]->(c:Character)-[:VOICED_BY]->(v:VoiceActor)
                    OPTIONAL MATCH (a)-[:PRODUCED_BY]->(s:Studio)
                    RETURN a,
                           collect(DISTINCT t.name)[..10] AS tags,
                           collect(DISTINCT c.name_cn)[..5]  AS chars,
                           collect(DISTINCT v.name)[..5]     AS vas,
                           collect(DISTINCT s.name)[..3]     AS studios
                    LIMIT 1
                """, id=int(anime_id)).single()
                if rec:
                    a = rec["a"]
                    graph_context = (
                        f"Anime: {a.get('name_cn') or a.get('name')}\n"
                        f"Score: {a.get('score')}  Rank: #{a.get('rank')}\n"
                        f"Tags: {', '.join(filter(None, rec['tags']))}\n"
                        f"Characters: {', '.join(filter(None, rec['chars']))}\n"
                        f"Voice Actors: {', '.join(filter(None, rec['vas']))}\n"
                        f"Studio: {', '.join(filter(None, rec['studios']))}\n"
                        f"Summary: {(a.get('summary') or '')[:400]}"
                    )
        except Exception:
            pass

    system_prompt = (
        "You are an expert anime assistant. Answer concisely and helpfully. "
        "When graph data is provided, ground your answer in it. "
        "Respond in the same language as the user's question."
    )
    messages = [{"role": "system", "content": system_prompt}]
    if graph_context:
        messages.append({"role": "system",
                         "content": f"Current anime context:\n{graph_context}"})
    messages.append({"role": "user", "content": question})

    def generate():
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": messages,
                      "stream": True, "max_tokens": 600},
                stream=True, timeout=30
            )
            source = "knowledge_graph" if graph_context else "general_model"
            for line in resp.iter_lines():
                if line and line.startswith(b"data: "):
                    chunk = line[6:]
                    if chunk == b"[DONE]":
                        yield f'data: {json.dumps({"done": True, "source": source})}\n\n'
                        return
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content","")
                        if delta:
                            yield f'data: {json.dumps({"token": delta})}\n\n'
                    except Exception:
                        pass
        except Exception:
            yield f'data: {json.dumps({"error": "AI error", "fallback": True})}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ── /identify ─────────────────────────────────────────────────────
@app.post("/identify")
def identify():
    """Screenshot identification via trace.moe."""
    if "image" not in request.files:
        return jsonify({"error": "no image uploaded"}), 400
    img  = request.files["image"]
    size = img.seek(0, 2); img.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify({"error": "image exceeds 5MB"}), 413
    if img.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify({"error": "unsupported format"}), 415

    try:
        resp = requests.post(
            "https://api.trace.moe/search?anilistInfo",
            files={"image": (img.filename, img.stream, img.mimetype)},
            timeout=10
        )
        if not resp.ok:
            return jsonify({"error": "identification service error", "matches": []}), 502

        matches = []
        for r in resp.json().get("result", [])[:3]:
            al    = r.get("anilist") or {}
            al_id = al.get("id") if isinstance(al, dict) else al
            title = (al.get("title", {}) if isinstance(al, dict) else {})
            sim   = round(r.get("similarity", 0), 3)

            in_graph = False
            neo4j_id = None
            if al_id:
                with driver.session() as session:
                    found = session.run(
                        "MATCH (a:Anime {anilist_id: $aid}) RETURN a.id AS id LIMIT 1",
                        aid=al_id
                    ).single()
                    if found:
                        in_graph = True
                        neo4j_id = found["id"]

            matches.append({
                "anilist_id": al_id,
                "anime_id":   neo4j_id,
                "anime_name": title.get("chinese") or title.get("romaji", ""),
                "episode":    r.get("episode"),
                "timestamp":  round(r.get("from", 0), 1),
                "similarity": sim,
                "in_graph":   in_graph,
            })
        return jsonify({"matches": matches})

    except requests.Timeout:
        return jsonify({"error": "identification service timeout"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
