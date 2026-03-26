# Anime GraphRAG Assistant — 产品需求文档 V2.1（修订版）

版本：V2.1
修订日期：2026-03-24
修订说明：对齐现有技术栈（Flask + Neo4j + HTML/JS），
         修正 RAG 落地方式，新增 Series Relation 智能功能，
         移除与现有项目不符的技术选型。

---

## 1. 项目定位

Anime GraphRAG Assistant 是一个融合 **Neo4j 知识图谱、外部动漫 API、
RAG 智能问答与截图识番**的二次元智能探索平台。

用户从单一入口（番剧名、截图、问题）出发，通过可视化的网状关联，
完成"看（详情）→ 问（AI）→ 找（识番）→ 跳（图谱漫游）→ 收藏"的探索闭环。

MVP 范围：
- 核心：图谱探索、侧栏详情、AI 问答、Series 关系探索
- 识番：接入 trace.moe API（不用 SauceNAO，场景不同）
- 平台：桌面端 Web 优先，移动端响应式

---

## 2. 技术选型（修正版）

| 领域 | 选型 | 说明 |
|------|------|------|
| 前端 | HTML + CSS + JavaScript（现有） | 保持现有代码，不切 React |
| 图谱库 | Cytoscape.js（现有） | report 要求，保持不变 |
| 后端框架 | Flask（现有） | 不切 FastAPI，保持现有 |
| 图数据库 | Neo4j AuraDB Free（现有） | 唯一数据库，移除 PostgreSQL |
| 向量检索 | ChromaDB（本地） | 替换 Milvus，课程项目够用 |
| LLM | OpenAI GPT-4o-mini | 比 GPT-3.5 便宜，能力更强 |
| 识番 API | trace.moe | 动漫截图专用，不用 SauceNAO |
| 动漫图片 | Jikan API（MAL 非官方） | 免费无 Key，获取封面图 |
| 动漫数据 | Bangumi API（现有 Token） | 已有 |

> 移除 PostgreSQL：用户收藏直接用 Neo4j 的 User 节点存储，
>                 不需要引入第二个数据库增加复杂度。
>
> 移除 Milvus：ChromaDB 本地运行，pip install chromadb 即可，
>             数据量 < 10 万条完全够用。

---

## 3. 数据库现状（已有数据，无需重新导入）

### Neo4j 节点
| 节点类型 | 数量 | 说明 |
|---------|------|------|
| Anime | ~6,500 | 动漫基本信息 |
| Character | ~25,000 | 角色（含 name_cn） |
| VoiceActor | ~数千 | 声优 |
| Tag | 28 个 | 标准化 tag |
| Studio | ~数百 | 制作公司 |
| Country | 少量 | 国家 |

### Neo4j 关系（已有）
- `(Anime)-[:HAS_CHARACTER]->(Character)`
- `(Character)-[:VOICED_BY]->(VoiceActor)`
- `(Anime)-[:HAS_TAG]->(Tag)`
- `(Anime)-[:PRODUCED_BY]->(Studio)`
- `(Anime)-[:ORIGIN_COUNTRY]->(Country)`

### 新增导入（V2.1 新增）
- `(Anime)-[:RELATED_TO {relation_type, same_series, group}]->(Anime)`
  来源：`anime_relations_fixed.csv`（9940 条，已清洗完毕）

---

## 4. 智能功能定义（7 个）

### 4.1 Function 1 — Graph Search（现有）
按名字搜索动漫/角色/声优，展示关联图谱。

### 4.2 Function 2 — Explainable Recommendation（现有，已升级）
基于 tag（×2）+ 声优（×3）+ 工作室（×1）加权推荐。
- 输入：动漫名字（自动补全，不再需要手输 ID）

### 4.3 Function 3 — Character Discovery（现有）
从角色出发，找同声优的其他作品。

### 4.4 Function 4 — Voice Actor Casting（现有）
按 tag 找擅长该类型的声优。

### 4.5 Function 5 — Series & Franchise Explorer（新增 ★）

**功能描述：**
用户输入一部动漫，系统展示该作品在系列中的位置，
并按关系类型分组显示所有关联作品。

**数据来源：** `anime_relations_fixed.csv` 导入的 `RELATED_TO` 边

**关系分组与颜色：**
| Group | 含义 | 包含关系类型 | 颜色 |
|-------|------|------------|------|
| main | 主线故事 | 前传、主线故事、续集 | 蓝色 |
| extra | 番外衍生 | 番外篇、衍生、角色出演、全集、动画 | 橙色 |
| skip | 可跳过 | 总集篇 | 灰色 |
| alt | 不同版本 | 不同演绎 | 紫色 |
| universe | 世界观 | 相同世界观、不同世界观、联动 | 青色 |

**前端交互：**
- 右侧 Detail Panel 新增 "Series" Tab
- 分组列出所有关联作品，点击任意作品跳转图谱
- 图谱边的颜色按 group 显示（5 种颜色）

**Cypher 查询：**
```cypher
MATCH (a:Anime {id:$id})-[r:RELATED_TO]->(b:Anime)
RETURN a, r, b
ORDER BY r.same_series DESC, r.relation_type
LIMIT 50
```

### 4.6 Function 6 — AI GraphRAG Assistant（新增 ★）

**功能描述：**
用户可以用自然语言提问，AI 结合知识图谱数据回答。

**RAG 实现流程（正确版）：**

```
用户问题
   ↓
1. 从 Neo4j 查询相关节点数据（Cypher）
   ↓
2. 将节点数据转成文本块，存入 ChromaDB 向量库
   （构建时一次性完成，不是每次查询都跑）
   ↓
3. 用户问题向量化，在 ChromaDB 里检索最相关的文本块
   ↓
4. 将检索到的上下文 + 用户问题 发给 GPT-4o-mini
   ↓
5. 返回回答，标注"数据来源：知识图谱"
```

**向量库构建方式：**
```python
# 把 Neo4j 数据转成文档
doc = f"""
番剧：{anime['name_cn']}
标签：{', '.join(tags)}
声优：{', '.join(vas)}
简介：{anime['summary']}
评分：{anime['score']} 排名：{anime['rank']}
"""
# 存入 ChromaDB
collection.add(documents=[doc], ids=[str(anime['id'])])
```

**上下文感知：**
- 用户正在查看某个节点时，自动把该节点数据注入对话上下文
- 输入框上方显示 Chip："当前聊天关于：进击的巨人"，可手动删除

**降级方案：**
- ChromaDB 检索失败 → 直接用 GPT 通用知识回答，标注"基于通用模型"

**Flask 接口：**
```python
@app.post("/ask")
def ask():
    question = request.json.get("question")
    context_id = request.json.get("anime_id")  # 可选
    # 1. 检索向量库
    # 2. 拼接 prompt
    # 3. 调用 OpenAI
    # 4. 返回答案
```

### 4.7 Function 7 — Screenshot Identification（新增 ★）

**功能描述：**
用户上传动漫截图，识别是哪部番的哪一集哪一秒，
然后直接在图谱里定位该节点。

**API：** trace.moe（完全免费，不需要 Key）
```
POST https://api.trace.moe/search
```

**交互流程：**
1. 上传截图（≤5MB，jpg/png/webp）
2. 调用 trace.moe，返回 AniList ID + 相似度
3. 用 AniList ID 在 Neo4j 里查对应 Anime 节点
   （需要提前在 Anime 节点上存一个 anilist_id 属性）
4. 高亮定位到图谱节点，右侧显示详情

**置信度处理：**
- ≥ 85%：直接定位，显示"识别结果：xxx"
- 60~85%：展示 Top3 候选，用户确认
- < 60%：提示"识别失败，请换一张更清晰的截图"

**注意：SauceNAO 是识别插画/同人图的，不适合动漫截图，移除。**

---

## 5. 侧栏 Detail Panel 结构（V2.1）

点击 Anime 节点后，右侧面板展示：

```
┌─────────────────────────────────┐
│  [封面图 via Jikan API]          │
│  进击的巨人                      │
│  ★ 9.1  #3  2013  WIT STUDIO   │
├─────────────────────────────────┤
│  [Info] [Series] [Ask AI]       │  ← Tab 切换
├─────────────────────────────────┤
│  Info Tab：                     │
│  简介文字...                    │
│  Tags: 战斗 奇幻 漫改           │
│                                 │
│  Series Tab（新增）：           │
│  主线故事                       │
│  · 进击的巨人 Season 2          │
│  · 进击的巨人 Season 3          │
│  番外衍生                       │
│  · 进击的巨人 OVA               │
│                                 │
│  Ask AI Tab：                   │
│  [这部番有什么特别的地方？]      │
│  [发送]                         │
├─────────────────────────────────┤
│  [推荐相似] [展开系列] [收藏]   │
└─────────────────────────────────┘
```

---

## 6. Jikan API 接入（获取封面图）

你的 Bangumi ID 和 MAL ID 不同，需要用名字搜索匹配：

```python
@app.get("/cover")
def get_cover():
    name = request.args.get("name", "")
    # 用动漫名搜索 Jikan
    r = requests.get(
        f"https://api.jikan.moe/v4/anime",
        params={"q": name, "limit": 1}
    )
    data = r.json()["data"]
    if data:
        return jsonify({
            "image": data[0]["images"]["jpg"]["large_image_url"],
            "mal_id": data[0]["mal_id"]
        })
    return jsonify({"image": None})
```

前端点击节点后异步拉取封面图，显示在 Detail Panel 顶部。

---

## 7. 开发优先级（适合课程项目的节奏）

| 优先级 | 功能 | 工作量 |
|--------|------|--------|
| P0 | 导入 anime_relations → RELATED_TO 边 | 0.5天 |
| P0 | Series Explorer（后端接口+前端展示） | 2天 |
| P0 | Jikan API 封面图接入 | 1天 |
| P1 | ChromaDB 向量库构建 | 1天 |
| P1 | AI 问答接口（/ask） | 2天 |
| P1 | 前端聊天窗 UI | 2天 |
| P2 | trace.moe 识番 | 1.5天 |
| P2 | 白色主题 UI 重构 | 2天 |

---

## 8. 移除的内容（相比 V2.0）

| 移除项 | 原因 |
|--------|------|
| PostgreSQL | 用户收藏用 Neo4j 即可，不需要第二个数据库 |
| Milvus | 过重，ChromaDB 足够 |
| SauceNAO | 用途是识别插画，不是动漫截图，和 trace.moe 不是同类 |
| React 18 + TypeScript | 重写成本太高，保持现有 HTML/JS |
| FastAPI | 保持现有 Flask |
| Pixi.js WebGL 渲染 | Cytoscape.js 已经够用，过度优化 |
| AniList 每日同步 | 你已有 Bangumi 数据，不需要重新同步 |

