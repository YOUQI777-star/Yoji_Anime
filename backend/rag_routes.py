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

from flask import Blueprint, Response, jsonify, request, stream_with_context

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

def _lazy_init():
    global _rag_ready, _answer, _classify, _retrieve, _oai, _cfg
    if _rag_ready:
        return True
    try:
        from scripts.rag.generator import answer as _a, _client, _load_api_key
        from scripts.rag.intent    import classify as _c
        from scripts.rag.retriever import retrieve as _r, _cfg as cfg
        _answer   = _a
        _classify = _c
        _retrieve = _r
        _oai      = _client
        _cfg      = cfg
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


# ── /rag/ask  (SSE 流式) ──────────────────────────────────────
@rag_bp.post("/ask")
def rag_ask():
    if not _lazy_init():
        return jsonify({"error": "RAG not ready"}), 503

    body      = request.get_json(silent=True) or {}
    question  = (body.get("question") or body.get("query") or "").strip()
    history   = body.get("history") or []          # [{role, content}, ...]
    user_name = (body.get("user_name") or "").strip()

    # graph_context 可能是前端传来的 dict，也可能是字符串
    _gc = body.get("graph_context")
    if isinstance(_gc, dict):
        import json as _json
        graph_context = _json.dumps(_gc, ensure_ascii=False)
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

        # 抽取推荐番名列表（graph blocks 的 title）
        rec_titles = [
            b["title"] for b in blocks
            if b.get("source") == "graph" and b.get("title")
        ]

        return jsonify({
            "answer":      result,
            "intent":      cls["intent"],
            "recommended": rec_titles,
            "blocks":      len(blocks),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
