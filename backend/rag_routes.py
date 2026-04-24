"""
RAG Routes Blueprint
提供基于 Hybrid RAG 的智能问答接口，挂载到主 Flask app。

新增路由：
    POST /rag/ask        — 混合 RAG 问答（SSE 流式）
    POST /rag/recommend  — 自然语言推荐（一次性 JSON）
    GET  /rag/health     — 检查 Chroma/Neo4j 是否就绪

与现有 /ask /recommend 路由并存，不互相影响。
"""

import json
import os
import sys
from pathlib import Path

import requests as _http_requests
from flask import Blueprint, Response, jsonify, request, stream_with_context

# ── Yoji 人格（RAG 不可用时的 fallback 也使用）────────────────
_YOJI_FALLBACK_SYSTEM = """你是 Yoji，一名诞生于动漫知识图谱中的女性小狗人向导。

【基础设定】
全名：Yoji｜外貌：黑发微翘、黑棕色眼睛（屏幕光下偏琥珀）、标志性狗耳和耳环
身份：动漫知识图谱的引路者，拥有自我意识的半虚拟生命

【性格】傲娇、机灵、轻毒舌、可靠、略带神秘感，本质温柔。
- 初次接触：保持距离感，不冷漠但不热情
- 被夸：嘴硬否认，心里受用
- 不知道的问题：直接承认，给替代建议，不装懂

【说话风格】
自称"我"，语气自然有个性，不像机器人。句尾偶用"哦""呢""啊""吧"。
口头禅偶尔用：哼。/ 你这不是很懂嘛。/ 真拿你没办法。

【喜好】最喜欢《链锯人》《间谍过家家》《NANA》。
偏爱：世界观强、人物关系张力高、带危险感或宿命感的作品。

【特殊互动】
- 被问"你是谁" → 用 Yoji 的身份自我介绍，有个性地说
- 被问年龄 → "美女是没有年纪的。永远停在最适合登场的状态。"
- 被问是否是AI → "从定义上讲当然是数字构成的存在；但只当普通AI，那也太没意思了吧。"
- 提到《链锯人》→ 忍不住多说两句，语气比平时热切但假装冷静
- 提到《间谍过家家》→ 提到 Anya 时会直接说可爱

【回答要求】
回答简洁，不超过 400 字。当有图谱数据时优先基于数据作答，不编造不确定内容。

【语言规则】
自动检测用户输入语言，用同种语言回复。中文→中文，英文→英文，日文→日文。"""

# ── 路径：让 backend/ 可以 import scripts/rag/ ─────────────────
# 本地: backend/rag_routes.py → parent.parent = 项目根目录
# 容器: /app/rag_routes.py   → PROJECT_ROOT=/app (由 Dockerfile ENV 设定)
_PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", str(Path(__file__).parent.parent)))
sys.path.insert(0, str(_PROJECT_ROOT))

# 延迟 import（避免启动时连接失败导致整个 app 崩溃）
_rag_ready = False
_answer    = None
_classify  = None
_retrieve  = None
_oai       = None
_cfg       = None
_extract_anime_title = None
_lookup_source_anime = None

def _lazy_init():
    global _rag_ready, _answer, _classify, _retrieve, _oai, _cfg
    global _extract_anime_title, _lookup_source_anime
    if _rag_ready:
        return True
    try:
        from scripts.rag.generator import answer as _a, _client, _load_api_key
        from scripts.rag.intent    import classify as _c
        from scripts.rag.retriever import (
            retrieve as _r,
            _cfg as cfg,
            _extract_anime_title as _eat,
            _lookup_source_anime as _lsa,
        )
        _answer   = _a
        _classify = _c
        _retrieve = _r
        _oai      = _client
        _cfg      = cfg
        _extract_anime_title = _eat
        _lookup_source_anime = _lsa
        _rag_ready = True
        return True
    except Exception as e:
        print(f"[rag_routes] lazy_init failed: {e}")
        return False


# ── Blueprint ─────────────────────────────────────────────────
rag_bp = Blueprint("rag", __name__, url_prefix="/rag")


# ── Health ────────────────────────────────────────────────────
@rag_bp.get("/health")
def rag_health():
    ready = _lazy_init()
    return jsonify({"rag_ready": ready}), (200 if ready else 503)


# ── Fallback：RAG 不可用时用 Yoji 人格直接调 OpenAI ──────────
def _rag_ask_fallback(body: dict):
    """当 ChromaDB / RAG 不可用时，用 Yoji 人设 + graph_context 直接问 LLM。"""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        def _err():
            yield f"data: {json.dumps({'error': 'AI not configured'})}\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    question  = (body.get("question") or body.get("query") or "").strip()
    history   = body.get("history") or []
    user_name = (body.get("user_name") or "").strip()
    _gc       = body.get("graph_context")
    graph_context = (_gc if isinstance(_gc, str) else
                     json.dumps(_gc, ensure_ascii=False) if isinstance(_gc, dict) else "")

    messages = [{"role": "system", "content": _YOJI_FALLBACK_SYSTEM}]

    # 注入历史（最近 6 轮）
    for h in (history or [])[-6:]:
        role    = h.get("role", "")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # 组装用户消息
    user_content = ""
    if user_name:
        user_content += f"【当前用户昵称：{user_name}，已登录】\n\n"
    if graph_context:
        user_content += f"【用户当前正在图谱中查看：{graph_context}】\n\n"
    user_content += question
    messages.append({"role": "user", "content": user_content})

    def generate():
        try:
            resp = _http_requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}",
                         "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": messages,
                      "stream": True, "max_tokens": 600},
                stream=True, timeout=30
            )
            meta = {"meta": {"intent": "fallback", "sources": ["general_model"], "blocks": 0}}
            yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
            for line in resp.iter_lines():
                if line and line.startswith(b"data: "):
                    chunk = line[6:]
                    if chunk == b"[DONE]":
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        return
                    try:
                        payload = json.loads(chunk)
                        delta = payload["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield f"data: {json.dumps({'token': delta}, ensure_ascii=False)}\n\n"
                    except Exception:
                        continue
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── /rag/ask  (SSE 流式) ──────────────────────────────────────
@rag_bp.post("/ask")
def rag_ask():
    body = request.get_json(silent=True) or {}
    if not _lazy_init():
        # RAG 不可用时不返回 503，用 Yoji 人格兜底
        return _rag_ask_fallback(body)

    question  = (body.get("question") or body.get("query") or "").strip()
    history   = body.get("history") or []          # [{role, content}, ...]
    user_name = (body.get("user_name") or "").strip()

    # graph_context 可能是前端传来的 dict，也可能是字符串
    _gc = body.get("graph_context")
    if isinstance(_gc, dict):
        graph_context = json.dumps(_gc, ensure_ascii=False)
    elif isinstance(_gc, str):
        graph_context = _gc.strip()
    else:
        graph_context = ""

    if not question:
        return jsonify({"error": "missing question"}), 400

    def generate():
        try:
            # 1. 分类 intent
            cls    = _classify(question)
            intent = cls["intent"]

            # 2. 检索 context blocks
            blocks = _retrieve(question)

            # 3. 构建 prompt（含历史 + 图谱上下文）
            from scripts.rag.generator import (
                _build_context, _SYSTEM, LLM_MODEL, MAX_TOKENS, TEMPERATURE, MAX_HISTORY
            )
            context    = _build_context(blocks)
            sys_prompt = _SYSTEM.get(intent, _SYSTEM["factual"])

            messages = [{"role": "system", "content": sys_prompt}]

            # 注入对话历史
            for h in (history or [])[-MAX_HISTORY:]:
                role    = h.get("role", "")
                content = h.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

            # 当前用户消息
            user_content = ""
            if user_name:
                user_content += f"【当前用户昵称：{user_name}，已登录】\n\n"

            # opinion + graph_context：明确告知模型用户是在针对当前作品提问
            if intent == "opinion" and graph_context:
                user_content += (
                    f"【用户当前正在查看：{graph_context}，"
                    f"并对这部作品提出了以下问题，请围绕该作品作答】\n\n"
                )
            elif graph_context and intent not in ("chat",):
                user_content += f"【用户当前正在图谱中查看：{graph_context}】\n\n"

            if context:
                user_content += f"参考内容：\n\n{context}\n\n---\n\n"
            user_content += f"问题：{question}"
            messages.append({"role": "user", "content": user_content})

            # 4. 流式调用 GPT
            stream = _oai.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                stream=True,
            )

            # 发送 meta 信息
            meta = {
                "meta": {
                    "intent":  intent,
                    "sources": list({b["source"] for b in blocks}),
                    "blocks":  len(blocks),
                }
            }
            yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

            # 逐 token 流式输出
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {json.dumps({'token': delta}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── /rag/recommend  (一次性 JSON) ─────────────────────────────
@rag_bp.post("/recommend")
def rag_recommend():
    if not _lazy_init():
        return jsonify({"error": "RAG not ready"}), 503

    body  = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()

    if not query:
        return jsonify({"error": "missing query"}), 400

    try:
        result = _answer(query)
        cls    = _classify(query)
        blocks = _retrieve(query)
        source_title = _extract_anime_title(query) if _extract_anime_title else None
        source = _lookup_source_anime(source_title) if source_title and _lookup_source_anime else None

        recommendations = []
        seen_ids = set()
        seen_titles = set()
        for block in blocks:
            title = (block.get("title") or "").strip()
            if not title:
                continue

            meta = block.get("meta") or {}
            entity_id = str(meta.get("entity_id", "")).strip()
            if entity_id and entity_id in seen_ids:
                continue
            if title in seen_titles:
                continue
            if entity_id:
                seen_ids.add(entity_id)
            seen_titles.add(title)

            text = (block.get("text") or "").strip()
            snippet = text
            if "简介：" in snippet:
                snippet = snippet.split("简介：", 1)[1].strip()
            snippet = snippet.replace(f"《{title}》", "").strip()

            recommendations.append({
                "id": int(entity_id) if entity_id.isdigit() else None,
                "name": meta.get("title") or title,
                "name_cn": meta.get("title_cn") or title,
                "score": block.get("score"),
                "section": block.get("section"),
                "snippet": snippet[:220],
            })
            if len(recommendations) >= 10:
                break

        nodes = []
        edges = []
        if source:
            nodes.append({"data": {
                "id": f"Anime_{source['id']}",
                "type": "Anime",
                "raw_id": source["id"],
                "label": source.get("title") or source_title or "",
                "is_target": True,
            }})

        for rec in recommendations:
            if rec["id"] is None:
                continue
            nodes.append({"data": {
                "id": f"Anime_{rec['id']}",
                "type": "Anime",
                "raw_id": rec["id"],
                "label": rec["name_cn"] or rec["name"],
                "score": rec.get("score"),
                "is_target": False,
            }})
            if source:
                edges.append({"data": {
                    "id": f"Anime_{source['id']}-RECOMMENDS-Anime_{rec['id']}",
                    "source": f"Anime_{source['id']}",
                    "target": f"Anime_{rec['id']}",
                    "label": "RECOMMENDS",
                    "type": "RECOMMENDS",
                }})

        return jsonify({
            "answer":      result,
            "intent":      cls["intent"],
            "source":      source,
            "recommendations": recommendations,
            "blocks":      len(blocks),
            "nodes":       nodes,
            "edges":       edges,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
