# ─────────────────────────────────────────────────────────────
# Yoji Anime Backend — 构建上下文为项目根目录
# 镜像内结构:
#   /app/              ← backend/ 的内容（app.py, rag_routes.py ...）
#   /app/scripts/      ← RAG pipeline (intent.py, retriever.py, generator.py ...)
#   /app/data/chroma_db/  ← 如果本地存在则复制（可选）
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 先只复制 requirements，利用 Docker 层缓存
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制 backend 主体（app.py, rag_routes.py, neo4j_client.py ...）
COPY backend/ .

# 复制 RAG 脚本
COPY scripts/ ./scripts/

# 复制 ChromaDB 向量库
COPY data/chroma_db/ ./data/chroma_db/

# 环境变量
# PROJECT_ROOT 让 retriever/generator/rag_routes 找到 scripts/ 目录
ENV PROJECT_ROOT=/app
ENV PORT=8080

EXPOSE 8080

# 单 worker：Chroma + Neo4j 连接不适合多进程共享
# timeout 180：LLM 调用最长约 30s，留足余量
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "180", "app:app"]
