import os
import time
import json
import uuid
import psycopg2
import psycopg2.extras
import secrets
import requests

from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response, stream_with_context, render_template
from flask_cors import CORS
from neo4j import GraphDatabase
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────
load_dotenv()

app = Flask(__name__)

# 如果你后面要限制来源，可以把 "*" 改成你的 Vercel 域名
CORS(app, resources={r"/*": {"origins": "*"}})

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
BANGUMI_TOKEN = os.getenv("BANGUMI_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PORT = int(os.getenv("PORT", 8080))

if not NEO4J_URI or not NEO4J_USER or not NEO4J_PASSWORD:
    raise ValueError("Missing Neo4j environment variables. Check backend/.env")

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD)
)

COVER_TTL = 3600
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
SUPPORTED_DISPLAY_LANGS = {"cn", "ori"}
EXPANDABLE_TYPES = {"Anime", "Character", "VoiceActor", "Tag", "Studio"}
FAVORITE_TYPES = {"Anime", "Character", "VoiceActor"}
FAVORITE_LIMIT = 10

_cover_cache = {}

DATABASE_URL = os.getenv("DATABASE_URL")


# ─────────────────────────────────────────────────────────────
# PostgreSQL: users / sessions / favorites
# ─────────────────────────────────────────────────────────────
def get_db_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def get_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_db_conn()
    cur = get_cursor(conn)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS favorites (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        item_type TEXT NOT NULL,
        item_raw_id TEXT NOT NULL,
        item_display_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, item_type, item_raw_id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# ─────────────────────────────────────────────────────────────
# General helpers
# ─────────────────────────────────────────────────────────────
def safe_limit(value, default=DEFAULT_LIMIT, max_limit=MAX_LIMIT):
    try:
        value = int(value)
    except Exception:
        value = default
    if value < 1:
        value = default
    return min(value, max_limit)


def safe_display_lang(value):
    value = (value or "cn").strip().lower()
    if value not in SUPPORTED_DISPLAY_LANGS:
        return "cn"
    return value


def now_iso():
    return datetime.utcnow().isoformat()


def run_query(query, params=None):
    with driver.session() as session:
        result = session.run(query, params or {})
        return [record.data() for record in result]


def get_node_raw_id(node):
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"

    if label in {"Anime", "Character"}:
        val = node.get("id")
        return str(val) if val is not None else None   # None = skip this node
    if label in {"VoiceActor", "Tag", "Studio", "Country"}:
        val = node.get("name")
        return str(val) if val is not None else None   # None = skip this node
    return str(node.element_id)


def get_node_display_label(node, display_lang="cn"):
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"

    if label in {"Anime", "Character"}:
        if display_lang == "ori":
            return node.get("name") or node.get("name_cn") or "Unknown"
        return node.get("name_cn") or node.get("name") or "Unknown"

    return node.get("name_cn") or node.get("name") or "Unknown"


def build_node_data(node, display_lang="cn"):
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    raw_id = get_node_raw_id(node)

    if raw_id is None:
        return None   # caller must skip None returns

    data = {
        "id": f"{label}:{raw_id}",
        "raw_id": raw_id,
        "type": label,
        "label": get_node_display_label(node, display_lang),
        "display_lang": display_lang,
    }

    for key in [
        "name", "name_cn", "score", "rank", "date",
        "episodes", "platform", "director", "summary"
    ]:
        if key in node and node.get(key) is not None:
            data[key] = node.get(key)

    return data


def build_graph_from_records(records, display_lang="cn"):
    nodes = {}
    edges = {}

    for record in records:
        for value in record.values():
            if value is None:
                continue

            if hasattr(value, "labels"):
                node_data = build_node_data(value, display_lang)
                if node_data is None:
                    continue
                nodes[node_data["id"]] = {"data": node_data}

            elif hasattr(value, "type") and hasattr(value, "start_node") and hasattr(value, "end_node"):
                start_node = value.start_node
                end_node = value.end_node

                start_data = build_node_data(start_node, display_lang)
                end_data = build_node_data(end_node, display_lang)

                # skip edges where either endpoint has no valid ID
                if start_data is None or end_data is None:
                    continue

                nodes[start_data["id"]] = {"data": start_data}
                nodes[end_data["id"]] = {"data": end_data}

                edge_id = f'{start_data["id"]}-{value.type}-{end_data["id"]}'
                if edge_id not in edges:
                    edge_payload = {
                        "id": edge_id,
                        "source": start_data["id"],
                        "target": end_data["id"],
                        "label": value.type,
                    }

                    for prop in ["relation", "relation_type", "same_series", "group"]:
                        try:
                            prop_val = value.get(prop)
                            if prop_val is not None:
                                edge_payload[prop] = prop_val
                        except Exception:
                            pass

                    edges[edge_id] = {"data": edge_payload}

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values())
    }


def graph_query(query, params=None, display_lang="cn"):
    with driver.session() as session:
        records = list(session.run(query, params or {}))
        return build_graph_from_records(records, display_lang)


def resolve_anime_id_by_name(name):
    if not name:
        return None

    query = """
    MATCH (a:Anime)
    WHERE toLower(coalesce(a.name, "")) CONTAINS toLower($q)
       OR toLower(coalesce(a.name_cn, "")) CONTAINS toLower($q)
    RETURN a.id AS id,
           a.name AS name,
           a.name_cn AS name_cn,
           a.rank AS rank
    ORDER BY
      CASE
        WHEN toLower(coalesce(a.name_cn, "")) = toLower($q) THEN 0
        WHEN toLower(coalesce(a.name, "")) = toLower($q) THEN 1
        ELSE 2
      END,
      a.rank ASC
    LIMIT 1
    """
    rows = run_query(query, {"q": name})
    return rows[0]["id"] if rows else None


def get_authorized_user():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.replace("Bearer ", "", 1).strip()
    if not token:
        return None

    conn = get_db_conn()
    cur = get_cursor(conn)
    cur.execute("""
    SELECT u.id, u.email, u.display_name, u.created_at
    FROM user_sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.token = %s
    """, (token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "created_at": row["created_at"],
        "token": token
    }


def auth_required():
    user = get_authorized_user()
    if not user:
        return None, (jsonify({"error": "unauthorized"}), 401)
    return user, None


def count_user_favorites(user_id):
    conn = get_db_conn()
    cur = get_cursor(conn)
    cur.execute("SELECT COUNT(*) AS cnt FROM favorites WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def normalize_favorite_payload(item_type, item_raw_id, item_display_name):
    item_type = (item_type or "").strip()
    item_raw_id = str(item_raw_id or "").strip()
    item_display_name = (item_display_name or "").strip()

    if item_type not in FAVORITE_TYPES:
        return None, "invalid item_type"
    if not item_raw_id:
        return None, "missing item_raw_id"
    if not item_display_name:
        return None, "missing item_display_name"

    return {
        "item_type": item_type,
        "item_raw_id": item_raw_id,
        "item_display_name": item_display_name
    }, None


# ─────────────────────────────────────────────────────────────
# Basic routes
# ─────────────────────────────────────────────────────────────
@app.get("/")
def home():
    return jsonify({"service": "anime-kg-api", "status": "ok"})


@app.get("/health")
def health():
    return jsonify({
        "service": "anime-kg-api",
        "status": "ok"
    })


@app.get("/db-health")
def db_health():
    rows = run_query("MATCH (a:Anime) RETURN count(a) AS anime_count")
    return jsonify({
        "status": "ok",
        "database": "connected",
        "result": rows
    })


# ─────────────────────────────────────────────────────────────
# Auth / User Home backend
# ─────────────────────────────────────────────────────────────
@app.post("/auth/register")
def register():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or "").strip()

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    if not display_name:
        display_name = email.split("@")[0]

    conn = get_db_conn()
    cur = get_cursor(conn)

    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "email already registered"}), 409

    user_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)

    cur.execute("""
    INSERT INTO users (id, email, password_hash, display_name, created_at)
    VALUES (%s, %s, %s, %s, %s)
    """, (
        user_id,
        email,
        generate_password_hash(password),
        display_name,
        now_iso()
    ))

    cur.execute("""
    INSERT INTO user_sessions (token, user_id, created_at)
    VALUES (%s, %s, %s)
    """, (
        token,
        user_id,
        now_iso()
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "message": "registered",
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "display_name": display_name,
            "favorite_limit": FAVORITE_LIMIT,
            "favorite_count": 0
        }
    })


@app.post("/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn = get_db_conn()
    cur = get_cursor(conn)
    cur.execute("""
    SELECT id, email, display_name, password_hash, created_at
    FROM users
    WHERE email = %s
    """, (email,))
    row = cur.fetchone()

    if not row or not check_password_hash(row["password_hash"], password):
        conn.close()
        return jsonify({"error": "invalid credentials"}), 401

    token = secrets.token_urlsafe(32)
    cur.execute("""
    INSERT INTO user_sessions (token, user_id, created_at)
    VALUES (%s, %s, %s)
    """, (token, row["id"], now_iso()))
    conn.commit()
    conn.close()

    favorite_count = count_user_favorites(row["id"])

    return jsonify({
        "message": "logged in",
        "token": token,
        "user": {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
            "favorite_limit": FAVORITE_LIMIT,
            "favorite_count": favorite_count
        }
    })


@app.post("/auth/logout")
def logout():
    user, error = auth_required()
    if error:
        return error

    conn = get_db_conn()
    cur = get_cursor(conn)
    cur.execute("DELETE FROM user_sessions WHERE token = %s", (user["token"],))
    conn.commit()
    conn.close()

    return jsonify({"message": "logged out"})


@app.get("/auth/me")
def me():
    user, error = auth_required()
    if error:
        return error

    favorite_count = count_user_favorites(user["id"])

    return jsonify({
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "created_at": user["created_at"],
        "favorite_limit": FAVORITE_LIMIT,
        "favorite_count": favorite_count
    })


@app.get("/favorites")
def list_favorites():
    user, error = auth_required()
    if error:
        return error

    conn = get_db_conn()
    cur = get_cursor(conn)
    cur.execute("""
    SELECT id, item_type, item_raw_id, item_display_name, created_at
    FROM favorites
    WHERE user_id = %s
    ORDER BY created_at DESC
    """, (user["id"],))
    rows = cur.fetchall()
    conn.close()

    grouped = {
        "Anime": [],
        "Character": [],
        "VoiceActor": []
    }

    for row in rows:
        grouped[row["item_type"]].append({
            "favorite_id": row["id"],
            "item_type": row["item_type"],
            "item_raw_id": row["item_raw_id"],
            "item_display_name": row["item_display_name"],
            "created_at": row["created_at"]
        })

    return jsonify({
        "favorite_limit": FAVORITE_LIMIT,
        "favorite_count": len(rows),
        "favorites": grouped
    })


@app.post("/favorites")
def add_favorite():
    user, error = auth_required()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    normalized, err = normalize_favorite_payload(
        body.get("item_type"),
        body.get("item_raw_id"),
        body.get("item_display_name")
    )
    if err:
        return jsonify({"error": err}), 400

    current_count = count_user_favorites(user["id"])
    if current_count >= FAVORITE_LIMIT:
        return jsonify({
            "error": "favorite limit reached",
            "favorite_limit": FAVORITE_LIMIT
        }), 400

    conn = get_db_conn()
    cur = get_cursor(conn)
    favorite_id = str(uuid.uuid4())

    try:
        cur.execute("""
        INSERT INTO favorites (id, user_id, item_type, item_raw_id, item_display_name, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            favorite_id,
            user["id"],
            normalized["item_type"],
            normalized["item_raw_id"],
            normalized["item_display_name"],
            now_iso()
        ))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.close()
        return jsonify({"error": "already favorited"}), 409

    conn.close()

    return jsonify({
        "message": "favorited",
        "favorite_id": favorite_id,
        "favorite_count": current_count + 1,
        "favorite_limit": FAVORITE_LIMIT
    })


@app.delete("/favorites/<favorite_id>")
def delete_favorite(favorite_id):
    user, error = auth_required()
    if error:
        return error

    conn = get_db_conn()
    cur = get_cursor(conn)
    cur.execute("""
    DELETE FROM favorites
    WHERE id = %s AND user_id = %s
    """, (favorite_id, user["id"]))
    deleted = cur.rowcount
    conn.commit()
    conn.close()

    if deleted == 0:
        return jsonify({"error": "favorite not found"}), 404

    return jsonify({
        "message": "favorite removed",
        "favorite_count": count_user_favorites(user["id"]),
        "favorite_limit": FAVORITE_LIMIT
    })


# ─────────────────────────────────────────────────────────────
# Search / autocomplete / tags
# ─────────────────────────────────────────────────────────────
@app.get("/search")
def search():
    query_text = request.args.get("query", "").strip()
    limit = safe_limit(request.args.get("limit", DEFAULT_LIMIT))
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))
    scope = (request.args.get("scope") or "all").strip().lower()

    if not query_text:
        return jsonify({
            "nodes": [],
            "edges": [],
            "error": "empty query"
        }), 400

    if query_text.isdigit() and scope in {"all", "anime"}:
        cypher = """
        MATCH (a:Anime {id: toInteger($id)})
        OPTIONAL MATCH (a)-[r]-(n)
        RETURN a, r, n
        LIMIT $limit
        """
        return jsonify(graph_query(
            cypher,
            {"id": query_text, "limit": limit},
            display_lang=display_lang
        ))

    union_parts = []

    if scope in {"all", "anime"}:
        union_parts.append("""
        MATCH (a:Anime)
        WHERE toLower(coalesce(a.name, "")) CONTAINS toLower($q)
           OR toLower(coalesce(a.name_cn, "")) CONTAINS toLower($q)
        RETURN a AS n
        """)

    if scope in {"all", "character"}:
        union_parts.append("""
        MATCH (c:Character)
        WHERE toLower(coalesce(c.name, "")) CONTAINS toLower($q)
           OR toLower(coalesce(c.name_cn, "")) CONTAINS toLower($q)
        RETURN c AS n
        """)

    if scope in {"all", "va", "voiceactor"}:
        union_parts.append("""
        MATCH (v:VoiceActor)
        WHERE toLower(coalesce(v.name, "")) CONTAINS toLower($q)
        RETURN v AS n
        """)

    if not union_parts:
        return jsonify({"nodes": [], "edges": [], "error": "invalid scope"}), 400

    cypher = f"""
    CALL {{
        {" UNION ".join(union_parts)}
    }}
    WITH DISTINCT n
    OPTIONAL MATCH (n)-[r]-(m)
    RETURN n, r, m
    LIMIT $limit
    """

    return jsonify(graph_query(
        cypher,
        {"q": query_text, "limit": limit},
        display_lang=display_lang
    ))


@app.get("/autocomplete")
def autocomplete():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    query = """
    MATCH (a:Anime)
    WHERE toLower(coalesce(a.name, "")) CONTAINS toLower($q)
       OR toLower(coalesce(a.name_cn, "")) CONTAINS toLower($q)
    RETURN a.id AS id, a.name AS name, a.name_cn AS name_cn, a.rank AS rank
    ORDER BY a.rank ASC
    LIMIT 10
    """
    rows = run_query(query, {"q": q})

    return jsonify([
        {
            "id": row["id"],
            "name": row["name"] or "",
            "name_cn": row["name_cn"] or "",
            "display": row["name_cn"] or row["name"] or ""
        }
        for row in rows
    ])


@app.get("/tags")
def tags():
    q = request.args.get("q", "").strip()
    limit = safe_limit(request.args.get("limit", 50), default=50, max_limit=200)

    if q:
        query = """
        MATCH (t:Tag)
        WHERE toLower(coalesce(t.name, "")) CONTAINS toLower($q)
        RETURN t.name AS name, count { (a:Anime)-[:HAS_TAG]->(t) } AS usage_count
        ORDER BY usage_count DESC, name ASC
        LIMIT $limit
        """
        rows = run_query(query, {"q": q, "limit": limit})
    else:
        query = """
        MATCH (t:Tag)
        RETURN t.name AS name, count { (a:Anime)-[:HAS_TAG]->(t) } AS usage_count
        ORDER BY usage_count DESC, name ASC
        LIMIT $limit
        """
        rows = run_query(query, {"limit": limit})

    return jsonify({
        "tags": rows
    })


# ─────────────────────────────────────────────────────────────
# Anime detail
# ─────────────────────────────────────────────────────────────
@app.get("/anime")
def anime_detail():
    anime_id = request.args.get("id", type=int)
    name = request.args.get("name", "").strip()

    if not anime_id and name:
        anime_id = resolve_anime_id_by_name(name)

    if not anime_id:
        return jsonify({"error": "missing id or name"}), 400

    query = """
    MATCH (a:Anime {id: $id})
    OPTIONAL MATCH (a)-[:HAS_TAG]->(t:Tag)
    OPTIONAL MATCH (a)-[:HAS_CHARACTER]->(c:Character)
    OPTIONAL MATCH (c)-[:VOICED_BY]->(v:VoiceActor)
    OPTIONAL MATCH (a)-[:PRODUCED_BY]->(s:Studio)
    OPTIONAL MATCH (a)-[:ORIGIN_COUNTRY]->(country:Country)
    OPTIONAL MATCH (a)-[rel:RELATED_TO]->(b:Anime)
    RETURN
      a.id AS id,
      a.name AS name,
      a.name_cn AS name_cn,
      a.date AS date,
      a.platform AS platform,
      a.score AS score,
      a.rank AS rank,
      a.episodes AS episodes,
      a.director AS director,
      a.summary AS summary,
      collect(DISTINCT t.name) AS tags,
      collect(DISTINCT c.name) AS character_names,
      collect(DISTINCT c.name_cn) AS character_names_cn,
      collect(DISTINCT v.name) AS voice_actors,
      collect(DISTINCT s.name) AS studios,
      collect(DISTINCT country.name) AS countries,
      collect(DISTINCT {
        target_id: b.id,
        target_name: b.name,
        target_name_cn: b.name_cn,
        relation_type: rel.relation_type,
        same_series: rel.same_series,
        group: rel.group
      }) AS relations
    """
    rows = run_query(query, {"id": anime_id})

    if not rows:
        return jsonify({"error": "anime not found"}), 404

    return jsonify(rows[0])


# ─────────────────────────────────────────────────────────────
# Expand
# ─────────────────────────────────────────────────────────────
@app.get("/expand")
def expand():
    raw_id = request.args.get("id", "").strip()
    node_type = request.args.get("type", "").strip()
    limit = safe_limit(request.args.get("limit", DEFAULT_LIMIT))
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))

    if not raw_id or not node_type:
        return jsonify({
            "nodes": [],
            "edges": [],
            "error": "missing id or type"
        }), 400

    if node_type not in EXPANDABLE_TYPES:
        return jsonify({
            "nodes": [],
            "edges": [],
            "error": f"unsupported type: {node_type}"
        }), 400

    if node_type == "Anime":
        cypher = """
        MATCH (a:Anime {id: toInteger($id)})
        OPTIONAL MATCH (a)-[r1:HAS_CHARACTER]->(c:Character)
        OPTIONAL MATCH (a)-[r2:HAS_TAG]->(t:Tag)
        OPTIONAL MATCH (a)-[r3:RELATED_TO]->(b:Anime)
        OPTIONAL MATCH (a)-[r4:PRODUCED_BY]->(s:Studio)
        OPTIONAL MATCH (a)-[r5:ORIGIN_COUNTRY]->(country:Country)
        RETURN a, r1, c, r2, t, r3, b, r4, s, r5, country
        LIMIT 300
        """
        result = graph_query(
            cypher,
            {"id": raw_id},
            display_lang=display_lang
        )

        # 后端统一做“分类型配额”裁剪，保证图谱更均衡
        all_nodes = result["nodes"]
        all_edges = result["edges"]

        center_nodes = [
            n for n in all_nodes
            if n["data"]["type"] == "Anime" and n["data"]["raw_id"] == str(raw_id)
        ]

        other_nodes = [
            n for n in all_nodes
            if not (n["data"]["type"] == "Anime" and n["data"]["raw_id"] == str(raw_id))
        ]

        characters = [n for n in other_nodes if n["data"]["type"] == "Character"]
        tags = [n for n in other_nodes if n["data"]["type"] == "Tag"]
        related_anime = [n for n in other_nodes if n["data"]["type"] == "Anime"]
        studios = [n for n in other_nodes if n["data"]["type"] == "Studio"]
        countries = [n for n in other_nodes if n["data"]["type"] == "Country"]
        others = [
            n for n in other_nodes
            if n["data"]["type"] not in {"Character", "Tag", "Anime", "Studio", "Country"}
        ]

        # 每类节点排序，保证输出稳定
        for group in [characters, tags, related_anime, studios, countries, others]:
            group.sort(key=lambda x: x["data"]["label"])

        remaining = max(0, limit - len(center_nodes))

        char_cap = min(len(characters), max(5, remaining // 2))
        tag_cap = min(len(tags), max(3, remaining // 5))
        rel_cap = min(len(related_anime), max(3, remaining // 5))
        studio_cap = min(len(studios), 3)
        country_cap = min(len(countries), 2)

        selected = []
        selected.extend(characters[:char_cap])
        selected.extend(tags[:tag_cap])
        selected.extend(related_anime[:rel_cap])
        selected.extend(studios[:studio_cap])
        selected.extend(countries[:country_cap])

        # 如果还有剩余名额，再按顺序补充
        selected_ids = {n["data"]["id"] for n in selected}
        leftover = [
            n for n in (characters + tags + related_anime + studios + countries + others)
            if n["data"]["id"] not in selected_ids
        ]

        slots_left = max(0, remaining - len(selected))
        selected.extend(leftover[:slots_left])

        kept_nodes = center_nodes + selected
        kept_node_ids = {n["data"]["id"] for n in kept_nodes}

        kept_edges = [
            e for e in all_edges
            if e["data"]["source"] in kept_node_ids and e["data"]["target"] in kept_node_ids
        ]

        result = {
            "nodes": kept_nodes,
            "edges": kept_edges,
            "requested_limit": limit,
            "display_lang": display_lang
        }
        return jsonify(result)

    if node_type == "Character":
        cypher = """
        MATCH (c:Character {id: $id})
        OPTIONAL MATCH (a:Anime)-[r1:HAS_CHARACTER]->(c)
        OPTIONAL MATCH (c)-[r2:VOICED_BY]->(v:VoiceActor)
        RETURN c, r1, a, r2, v
        LIMIT $limit
        """
        return jsonify(graph_query(
            cypher,
            {"id": raw_id, "limit": limit},
            display_lang=display_lang
        ))

    if node_type == "VoiceActor":
        cypher = """
        MATCH (v:VoiceActor {name: $id})
        OPTIONAL MATCH (c:Character)-[r1:VOICED_BY]->(v)
        OPTIONAL MATCH (a:Anime)-[r2:HAS_CHARACTER]->(c)
        RETURN v, r1, c, r2, a
        LIMIT $limit
        """
        return jsonify(graph_query(
            cypher,
            {"id": raw_id, "limit": limit},
            display_lang=display_lang
        ))

    if node_type == "Tag":
        cypher = """
        MATCH (t:Tag {name: $id})
        OPTIONAL MATCH (a:Anime)-[r:HAS_TAG]->(t)
        RETURN t, r, a
        LIMIT $limit
        """
        return jsonify(graph_query(
            cypher,
            {"id": raw_id, "limit": limit},
            display_lang=display_lang
        ))

    if node_type == "Studio":
        cypher = """
        MATCH (s:Studio {name: $id})
        OPTIONAL MATCH (a:Anime)-[r:PRODUCED_BY]->(s)
        RETURN s, r, a
        LIMIT $limit
        """
        return jsonify(graph_query(
            cypher,
            {"id": raw_id, "limit": limit},
            display_lang=display_lang
        ))

    return jsonify({
        "nodes": [],
        "edges": [],
        "error": "unsupported type"
    }), 400

# ─────────────────────────────────────────────────────────────
# Recommend / relations / explanations
# ─────────────────────────────────────────────────────────────
@app.get("/recommend")
def recommend():
    anime_id = request.args.get("id", type=int)
    anime_name = request.args.get("name", "").strip()
    limit = safe_limit(request.args.get("limit", 10), default=10, max_limit=30)
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))

    if not anime_id and anime_name:
        anime_id = resolve_anime_id_by_name(anime_name)

    if not anime_id:
        return jsonify({
            "nodes": [],
            "edges": [],
            "recommendations": [],
            "error": "missing id or name"
        }), 400

    explanation_query = """
    MATCH (target:Anime {id: $id})
    MATCH (rec:Anime)
    WHERE rec.id <> target.id

      AND NOT EXISTS {
        MATCH (target)-[r:RELATED_TO]-(rec)
        WHERE coalesce(r.same_series, 0) = 1
      }

      AND NOT EXISTS {
        MATCH (target)-[r:RELATED_TO]-(rec)
        WHERE toLower(coalesce(r.relation_type, "")) IN [
          "sequel", "prequel", "spinoff", "side story", "side_story",
          "movie", "film", "theatrical", "ova", "oad", "special",
          "season", "part", "chapter"
        ]
           OR toLower(coalesce(r.group, "")) IN [
          "sequel", "prequel", "spinoff", "side story", "side_story",
          "movie", "film", "theatrical", "ova", "oad", "special",
          "season", "part", "chapter"
        ]
      }

    OPTIONAL MATCH (target)-[:HAS_TAG]->(t:Tag)<-[:HAS_TAG]-(rec)
    WITH target, rec, count(DISTINCT t) AS shared_tags

    OPTIONAL MATCH (target)-[:HAS_CHARACTER]->(:Character)-[:VOICED_BY]->(va:VoiceActor)
                   <-[:VOICED_BY]-(:Character)<-[:HAS_CHARACTER]-(rec)
    WITH target, rec, shared_tags, count(DISTINCT va) AS shared_voice_actors

    OPTIONAL MATCH (target)-[:PRODUCED_BY]->(s:Studio)<-[:PRODUCED_BY]-(rec)
    WITH target, rec, shared_tags, shared_voice_actors, count(DISTINCT s) AS shared_studios

    WITH target, rec,
         shared_tags,
         shared_voice_actors,
         shared_studios,
         shared_tags * 2 + shared_voice_actors * 3 + shared_studios AS final_score
    WHERE final_score > 0
    RETURN
      rec.id AS id,
      rec.name AS name,
      rec.name_cn AS name_cn,
      rec.rank AS rank,
      rec.score AS score,
      shared_tags,
      shared_voice_actors,
      shared_studios,
      final_score
    ORDER BY final_score DESC, rec.rank ASC
    LIMIT $limit
    """
    recommendations = run_query(explanation_query, {"id": anime_id, "limit": limit})

    if not recommendations:
        return jsonify({
            "nodes": [],
            "edges": [],
            "recommendations": []
        })

    rec_ids = [row["id"] for row in recommendations]

    graph_query_text = """
    MATCH (target:Anime {id: $id})
    MATCH (rec:Anime)
    WHERE rec.id IN $rec_ids
    OPTIONAL MATCH (target)-[r1]-(x)
    OPTIONAL MATCH (rec)-[r2]-(y)
    RETURN target, rec, r1, x, r2, y
    LIMIT 400
    """
    graph_result = graph_query(
        graph_query_text,
        {"id": anime_id, "rec_ids": rec_ids},
        display_lang=display_lang
    )

    return jsonify({
        "recommendations": [
            {
                "id": row["id"],
                "name": row["name"],
                "name_cn": row["name_cn"],
                "rank": row["rank"],
                "score": row["score"],
                "explanation": {
                    "shared_tags": row["shared_tags"],
                    "shared_voice_actors": row["shared_voice_actors"],
                    "shared_studios": row["shared_studios"],
                    "final_score": row["final_score"]
                }
            }
            for row in recommendations
        ],
        "nodes": graph_result["nodes"],
        "edges": graph_result["edges"]
    })


@app.get("/relations")
def relations():
    anime_id = request.args.get("id", type=int)
    group = request.args.get("group", "").strip()
    limit = safe_limit(request.args.get("limit", 50), default=50, max_limit=100)
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))

    if not anime_id:
        return jsonify({
            "nodes": [],
            "edges": [],
            "error": "missing id"
        }), 400

    if group:
        cypher = """
        MATCH (a:Anime {id: $id})-[r:RELATED_TO]->(b:Anime)
        WHERE r.group = $group
        RETURN a, r, b
        ORDER BY r.same_series DESC, r.relation_type
        LIMIT $limit
        """
        params = {"id": anime_id, "group": group, "limit": limit}
    else:
        cypher = """
        MATCH (a:Anime {id: $id})-[r:RELATED_TO]->(b:Anime)
        RETURN a, r, b
        ORDER BY r.same_series DESC, r.relation_type
        LIMIT $limit
        """
        params = {"id": anime_id, "limit": limit}

    return jsonify(graph_query(cypher, params, display_lang=display_lang))


# ─────────────────────────────────────────────────────────────
# Other graph routes
# ─────────────────────────────────────────────────────────────
@app.get("/character")
def character_discovery():
    name = request.args.get("name", "").strip()
    limit = safe_limit(request.args.get("limit", DEFAULT_LIMIT))
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))

    if not name:
        return jsonify({
            "nodes": [],
            "edges": [],
            "error": "missing name"
        }), 400

    cypher = """
    MATCH (c:Character)
    WHERE toLower(coalesce(c.name, "")) = toLower($name)
       OR toLower(coalesce(c.name_cn, "")) = toLower($name)
    MATCH (a:Anime)-[:HAS_CHARACTER]->(c)
    OPTIONAL MATCH (c)-[:VOICED_BY]->(va:VoiceActor)<-[:VOICED_BY]-(other:Character)
    OPTIONAL MATCH (rec:Anime)-[:HAS_CHARACTER]->(other)
    RETURN c, a, va, other, rec
    LIMIT $limit
    """
    return jsonify(graph_query(
        cypher,
        {"name": name, "limit": limit},
        display_lang=display_lang
    ))


@app.get("/studio")
def studio_style():
    name = request.args.get("name", "").strip()
    limit = safe_limit(request.args.get("limit", DEFAULT_LIMIT))
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))

    if not name:
        return jsonify({
            "nodes": [],
            "edges": [],
            "error": "missing name"
        }), 400

    cypher = """
    MATCH (s:Studio {name: $name})<-[:PRODUCED_BY]-(a:Anime)
    OPTIONAL MATCH (a)-[:HAS_TAG]->(t:Tag)
    RETURN s, a, t
    LIMIT $limit
    """
    return jsonify(graph_query(
        cypher,
        {"name": name, "limit": limit},
        display_lang=display_lang
    ))


@app.get("/casting")
def casting():
    tags = request.args.get("tags", "").strip()
    limit = safe_limit(request.args.get("limit", 20), default=20, max_limit=50)
    per_va_limit = safe_limit(request.args.get("per_va_limit", 10), default=10, max_limit=10)
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    if not tag_list:
        return jsonify({
            "voice_actor_summary": [],
            "nodes": [],
            "edges": [],
            "error": "missing tags"
        }), 400

    # 1) 声优摘要：不只看“配得多”，还考虑高排名作品权重
    summary_query = """
    MATCH (va:VoiceActor)<-[:VOICED_BY]-(c:Character)<-[:HAS_CHARACTER]-(a:Anime)-[:HAS_TAG]->(t:Tag)
    WHERE t.name IN $tags

    WITH va, a, count(DISTINCT t) AS anime_matched_tag_count

    WITH
      va,
      collect(DISTINCT a) AS matched_anime_list,
      sum(
        CASE
          WHEN a.rank IS NULL OR a.rank = 0 THEN 0
          WHEN a.rank <= 50 THEN 5
          WHEN a.rank <= 100 THEN 4
          WHEN a.rank <= 300 THEN 3
          WHEN a.rank <= 1000 THEN 2
          ELSE 1
        END
      ) AS weighted_rank_score,
      sum(anime_matched_tag_count) AS matched_tag_count

    WITH
      va,
      size(matched_anime_list) AS matched_anime_count,
      matched_tag_count,
      weighted_rank_score

    WITH
      va,
      matched_anime_count,
      matched_tag_count,
      weighted_rank_score,
      (weighted_rank_score * 2.0 + matched_tag_count + matched_anime_count * 0.5) AS summary_score

    RETURN
      va.name AS name,
      matched_anime_count,
      matched_tag_count,
      weighted_rank_score,
      summary_score
    ORDER BY summary_score DESC, matched_anime_count DESC, va.name ASC
    LIMIT $limit
    """
    summary_rows = run_query(summary_query, {
        "tags": tag_list,
        "limit": limit
    })

    if not summary_rows:
        return jsonify({
            "voice_actor_summary": [],
            "nodes": [],
            "edges": []
        })

    va_names = [row["name"] for row in summary_rows]

    # 2) Graph 候选：先把候选角色全部按优先级排好
    graph_candidate_query = """
    MATCH (va:VoiceActor)
    WHERE va.name IN $va_names

    MATCH (c:Character)-[r:VOICED_BY]->(va)
    MATCH (a:Anime)-[:HAS_CHARACTER]->(c)

    RETURN
      va.name AS va_name,
      va,
      r,
      c,
      a
    ORDER BY
      va.name ASC,
      CASE WHEN a.rank IS NULL OR a.rank = 0 THEN 999999 ELSE a.rank END ASC,
      a.score DESC,
      coalesce(c.name_cn, c.name, "") ASC
    LIMIT 3000
    """

    with driver.session() as session:
        candidate_records = list(session.run(
            graph_candidate_query,
            {"va_names": va_names}
        ))

    # 3) Python 里做“角色名去重”
    #    同一个声优下，同一个角色显示名只保留 rank 最好的那个版本
    selected_records = []
    records_by_va = {}

    for record in candidate_records:
        va_name = record["va_name"]
        records_by_va.setdefault(va_name, []).append(record)

    for va_name in va_names:
        va_records = records_by_va.get(va_name, [])

        seen_role_names = set()
        kept = []

        for record in va_records:
            character_node = record["c"]
            role_key = (
                character_node.get("name_cn")
                or character_node.get("name")
                or character_node.get("id")
            )

            if role_key in seen_role_names:
                continue

            seen_role_names.add(role_key)
            kept.append(record)

            if len(kept) >= per_va_limit:
                break

        selected_records.extend(kept)

    # 4) 转 graph
    graph_result = build_graph_from_records(selected_records, display_lang=display_lang)

    return jsonify({
        "voice_actor_summary": [
            {
                "name": row["name"],
                "matched_anime_count": row["matched_anime_count"],
                "matched_tag_count": row["matched_tag_count"],
                "weighted_rank_score": row["weighted_rank_score"],
                "summary_score": row["summary_score"]
            }
            for row in summary_rows
        ],
        "nodes": graph_result["nodes"],
        "edges": graph_result["edges"]
    })

@app.get("/niche")
def niche():
    min_rank = request.args.get("pop", 500, type=int)
    min_tags = request.args.get("rich", 5, type=int)
    limit = safe_limit(request.args.get("limit", DEFAULT_LIMIT))
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))

    cypher = """
    MATCH (a:Anime)-[:HAS_TAG]->(t:Tag)
    WITH a, count(DISTINCT t) AS richness
    WHERE a.rank >= $min_rank AND richness >= $min_tags
    MATCH (a)-[r:HAS_TAG]->(tag:Tag)
    RETURN a, r, tag
    LIMIT $limit
    """
    return jsonify(graph_query(
        cypher,
        {"min_rank": min_rank, "min_tags": min_tags, "limit": limit},
        display_lang=display_lang
    ))


# ─────────────────────────────────────────────────────────────
# Cover
# ─────────────────────────────────────────────────────────────
@app.get("/cover")
def cover():
    anime_id = request.args.get("id", type=int)
    if not anime_id:
        return jsonify({"image_url": None}), 400

    cached = _cover_cache.get(anime_id)
    if cached and time.time() - cached["ts"] < COVER_TTL:
        return jsonify({
            "image_url": cached["url"],
            "source": "cache"
        })

    headers = {"User-Agent": "anime-kg/1.0"}
    if BANGUMI_TOKEN:
        headers["Authorization"] = f"Bearer {BANGUMI_TOKEN}"

    try:
        resp = requests.get(
            f"https://api.bgm.tv/v0/subjects/{anime_id}",
            headers=headers,
            timeout=5
        )
        if resp.ok:
            images = resp.json().get("images", {})
            url = images.get("large") or images.get("medium") or images.get("small")
            _cover_cache[anime_id] = {"url": url, "ts": time.time()}
            return jsonify({
                "image_url": url,
                "source": "bangumi"
            })
    except Exception:
        pass

    _cover_cache[anime_id] = {"url": None, "ts": time.time()}
    return jsonify({
        "image_url": None,
        "source": "fallback"
    })


# ─────────────────────────────────────────────────────────────
# Ask (AI)
# ─────────────────────────────────────────────────────────────
@app.post("/ask")
def ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    anime_id = body.get("anime_id")

    if not question:
        return jsonify({"error": "missing question"}), 400

    if not OPENAI_API_KEY:
        return jsonify({
            "error": "AI not configured",
            "fallback": True
        }), 503

    graph_context = ""
    if anime_id:
        rows = run_query("""
        MATCH (a:Anime {id: $id})
        OPTIONAL MATCH (a)-[:HAS_TAG]->(t:Tag)
        OPTIONAL MATCH (a)-[:HAS_CHARACTER]->(c:Character)
        OPTIONAL MATCH (c)-[:VOICED_BY]->(v:VoiceActor)
        OPTIONAL MATCH (a)-[:PRODUCED_BY]->(s:Studio)
        RETURN a,
               collect(DISTINCT t.name)[0..10] AS tags,
               collect(DISTINCT c.name_cn)[0..5] AS chars,
               collect(DISTINCT v.name)[0..5] AS vas,
               collect(DISTINCT s.name)[0..3] AS studios
        """, {"id": int(anime_id)})

        if rows:
            row = rows[0]
            a = row["a"]
            graph_context = (
                f"Anime: {a.get('name_cn') or a.get('name')}\n"
                f"Score: {a.get('score')} Rank: #{a.get('rank')}\n"
                f"Tags: {', '.join([x for x in row['tags'] if x])}\n"
                f"Characters: {', '.join([x for x in row['chars'] if x])}\n"
                f"Voice Actors: {', '.join([x for x in row['vas'] if x])}\n"
                f"Studios: {', '.join([x for x in row['studios'] if x])}\n"
                f"Summary: {(a.get('summary') or '')[:500]}"
            )

    messages = [
        {
            "role": "system",
            "content": (
                "You are an anime assistant. "
                "Answer clearly and ground your answer in the provided graph data when available. "
                "Respond in the same language as the user."
            )
        },
        {"role": "user", "content": question}
    ]

    if graph_context:
        messages.insert(1, {
            "role": "system",
            "content": f"Graph context:\n{graph_context}"
        })

    def generate():
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 600
                },
                stream=True,
                timeout=30
            )

            source = "knowledge_graph" if graph_context else "general_model"

            for line in resp.iter_lines():
                if line and line.startswith(b"data: "):
                    chunk = line[6:]
                    if chunk == b"[DONE]":
                        yield f'data: {json.dumps({"done": True, "source": source})}\n\n'
                        return
                    try:
                        payload = json.loads(chunk)
                        delta = payload["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield f'data: {json.dumps({"token": delta})}\n\n'
                    except Exception:
                        continue
        except Exception:
            yield f'data: {json.dumps({"error": "AI error", "fallback": True})}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


# ─────────────────────────────────────────────────────────────
# Identify
# ─────────────────────────────────────────────────────────────
@app.post("/identify")
def identify():
    if "image" not in request.files:
        return jsonify({"error": "no image uploaded"}), 400

    img = request.files["image"]
    size = img.seek(0, 2)
    img.seek(0)

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
            return jsonify({
                "error": "identification service error",
                "matches": []
            }), 502

        matches = []
        for r in resp.json().get("result", [])[:3]:
            al = r.get("anilist") or {}
            al_id = al.get("id") if isinstance(al, dict) else al
            title = al.get("title", {}) if isinstance(al, dict) else {}
            sim = round(r.get("similarity", 0), 3)

            in_graph = False
            neo4j_id = None

            if al_id:
                rows = run_query(
                    "MATCH (a:Anime {anilist_id: $aid}) RETURN a.id AS id LIMIT 1",
                    {"aid": al_id}
                )
                if rows:
                    in_graph = True
                    neo4j_id = rows[0]["id"]

            matches.append({
                "anilist_id": al_id,
                "anime_id": neo4j_id,
                "anime_name": title.get("chinese") or title.get("romaji", ""),
                "episode": r.get("episode"),
                "timestamp": round(r.get("from", 0), 1),
                "similarity": sim,
                "in_graph": in_graph
            })

        return jsonify({"matches": matches})

    except requests.Timeout:
        return jsonify({"error": "identification service timeout"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Tag search & Watch order
# ─────────────────────────────────────────────────────────────
@app.get("/anime_by_tag")
def anime_by_tag():
    tags_param  = request.args.get("tag", "").strip()
    limit       = safe_limit(request.args.get("limit", 20), default=20, max_limit=50)
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))
    tag_list = [t.strip() for t in tags_param.split(",") if t.strip()]
    if not tag_list:
        return jsonify({"anime": [], "error": "missing tag"}), 400

    cypher = """
    MATCH (a:Anime)-[:HAS_TAG]->(t:Tag)
    WHERE t.name IN $tags AND a.id IS NOT NULL
    WITH a, collect(t.name) AS matched_tags
    RETURN a.id AS id, a.name AS name, a.name_cn AS name_cn,
           a.score AS score, a.rank AS rank, matched_tags
    ORDER BY
      CASE WHEN a.rank IS NULL OR a.rank = 0 THEN 99999 ELSE a.rank END ASC,
      CASE WHEN a.score IS NULL THEN 0 ELSE a.score END DESC
    LIMIT $limit
    """
    rows = run_query(cypher, {"tags": tag_list, "limit": limit})
    anime_list = []
    for row in rows:
        name = (row.get("name_cn") or row.get("name") or "") if display_lang == "cn" \
               else (row.get("name") or row.get("name_cn") or "")
        anime_list.append({
            "id": row["id"],
            "name": name,
            "score": row.get("score"),
            "rank": row.get("rank"),
            "matched_tags": row.get("matched_tags", [])
        })
    return jsonify({"anime": anime_list, "tags": tag_list})


@app.get("/watch_order")
def watch_order():
    anime_id     = request.args.get("id", type=int)
    display_lang = safe_display_lang(request.args.get("display_lang", "cn"))
    if not anime_id:
        return jsonify({"error": "missing id"}), 400

    target_rows = run_query(
        "MATCH (a:Anime {id: $id}) RETURN a.id AS id, a.name AS name, "
        "a.name_cn AS name_cn, a.score AS score, a.rank AS rank",
        {"id": anime_id}
    )
    if not target_rows:
        return jsonify({"error": "anime not found"}), 404

    t = target_rows[0]
    target_name = (t.get("name_cn") or t.get("name") or "") if display_lang == "cn" \
                  else (t.get("name") or t.get("name_cn") or "")
    target = {"id": t["id"], "name": target_name,
              "score": t.get("score"), "rank": t.get("rank")}

    rows = run_query("""
    MATCH (a:Anime {id: $id})-[r:RELATED_TO]-(b:Anime)
    WHERE b.id IS NOT NULL
    RETURN b.id AS id, b.name AS name, b.name_cn AS name_cn,
           b.score AS score, b.rank AS rank,
           r.relation_type AS relation_type, r.group AS grp
    """, {"id": anime_id})

    prequel_rels = {"前传", "prequel"}
    sequel_rels  = {"续集", "sequel"}
    main_order, side_stories = [], []
    seen_ids = set()
    for row in rows:
        grp = row.get("grp") or ""
        if not grp or grp in ("alt", "universe") or row["id"] in seen_ids:
            continue
        seen_ids.add(row["id"])
        name = (row.get("name_cn") or row.get("name") or "") if display_lang == "cn" \
               else (row.get("name") or row.get("name_cn") or "")
        item = {"id": row["id"], "name": name,
                "relation": row.get("relation_type") or "",
                "score": row.get("score"), "rank": row.get("rank")}
        if grp == "main":
            main_order.append(item)
        else:
            side_stories.append(item)

    main_order.sort(key=lambda x: (
        0 if x["relation"] in prequel_rels else
        2 if x["relation"] in sequel_rels else 1
    ))
    prequel_count = sum(1 for x in main_order if x["relation"] in prequel_rels)
    main_order.insert(prequel_count, {**target, "relation": "本作", "is_target": True})

    return jsonify({
        "target": target,
        "main_order": main_order,
        "side_stories": side_stories,
        "note": "根据现有 relationship 自动整理，供参考"
    })


# ─────────────────────────────────────────────────────────────
# RAG Blueprint（Hybrid RAG：Chroma + Neo4j + GPT）
# ─────────────────────────────────────────────────────────────
try:
    from rag_routes import rag_bp
    app.register_blueprint(rag_bp)
    print("[app] RAG blueprint registered → /rag/ask  /rag/recommend  /rag/health")
except Exception as _rag_err:
    print(f"[app] RAG blueprint skipped (missing deps?): {_rag_err}")


# ─────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)