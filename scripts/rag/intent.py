"""
查询意图分类器
将用户输入分为三种 intent：
  - factual   : 事实性问题（剧情/角色/导演/集数…）
  - recommend : 推荐请求（找类似的/有哪些/给我推荐…）
  - relation  : 关系查询（同声优/同系列/同制作公司…）

返回值: {"intent": "factual"|"recommend"|"relation", "entities": {...}}
  entities 里包含识别到的 anime_title、voice_actor、studio、tag 等

运行方式：
    python scripts/rag/intent.py "推荐几部和进击的巨人类似的番"
"""

import re
import sys
from typing import Literal

# ──────────────────────────── 规则表 ──────────────────────────
RECOMMEND_PATTERNS = [
    r"推荐",
    r"类似",
    r"像.{0,10}(一样|那样|这样)",
    r"有没有.{0,10}(番|动漫|动画)",
    r"找.{0,10}(番|动漫|动画)",
    r"想看.{0,15}(的番|动漫|动画)",
    r"想看.{0,20}(系|类型|风格)",   # 补：「想看治愈系」「想看悬疑风格」等不带「的番」结尾
    r"好看的",
    r"哪些.{0,10}(番|动漫|动画)",
    r"similar|recommend",
    r"适合.{0,10}看",
    r"风格.{0,10}(像|类似|相近)",
    r"同类",
    # 明确风格词直接触发推荐（不依赖句式）
    r"(治愈|日常|热血|悬疑|烧脑|搞笑|恐怖|校园|奇幻|异世界|isekai|后宫|百合|机甲|运动).{0,10}(番|动漫|动画|的)",
]

RELATION_PATTERNS = [
    r"同.*声优",
    r"同.*系列",
    r"同.*制作",
    r"同.*导演",
    r"同.*公司",
    r"系列.{0,5}(作品|有哪些|是什么)",
    r"(有哪些|什么).{0,5}系列",
    r"related|sequel|prequel|spin.?off",
    r"前传|续集|衍生",
    r"配过.{0,6}(角色|什么|哪些)",
    r"声优.*配",
    r"出演过",
    r"[\u3040-\u30ff\u4e00-\u9fff]{2,8}配过",  # 「名字配过」
]

FACTUAL_PATTERNS = [
    r"讲什么|讲的是|剧情",
    r"什么时候.*播|首播|上映",
    r"几集|多少集",
    r"导演|监督",
    r"制作公司|制作方|studio",
    r"主角|角色|人物",
    r"评分|分数|score",
    r"简介|介绍|overview",
    r"第\s*[一二三四五六七八九十\d]+\s*季",
]

# 闲聊：不涉及动漫知识，纯日常对话
CHAT_PATTERNS = [
    r"^(你好|hi|hello|嗨|哈喽|早上好|晚上好|下午好|good\s*(morning|evening|night|afternoon))",
    r"^(哈哈|哈哈哈|lol|笑死)",
    r"你叫什么|你是谁|你多大|介绍.{0,3}自己",
    r"你(喜欢|讨厌|爱|恨).{0,5}(什么|哪|谁)",
    r"你(今天|最近|现在)怎么样",
    r"(陪我|聊聊天|说说话|无聊)",
    r"(谢谢|感谢|thank)",
    r"(再见|拜拜|bye|晚安|good\s*night)",
    r"^(哦|哦哦|嗯|嗯嗯|好的|ok|okay|好)$",
]

# 主观评价：问 Yoji 对某作品/角色的看法
OPINION_PATTERNS = [
    r"你(觉得|认为|感觉|怎么看|喜欢吗|好看吗|值得看吗)",
    r"(好看吗|值得看吗|推荐吗|怎么样|如何).{0,5}$",
    r"你(最喜欢|最爱|最讨厌|最不喜欢)",
    r"(哪个|哪部|哪个角色).{0,10}(更好|更喜欢|更厉害|比较)",
    r"(烂|垃圾|神作|经典|好哭|感人|无聊).{0,5}吗",
    r"你的(看法|评价|意见|观点)",
]

# 实体抽取简单规则（用于图查询补充）
VOICE_ACTOR_KW = ["声优", "cv", "配音"]
STUDIO_KW      = ["制作", "工作室", "动画公司", "京阿尼", "MAPPA", "ufotable",
                   "骨头社", "A-1", "Production I.G", "Shaft", "KyoAni"]
SERIES_KW      = ["系列", "前传", "续集", "衍生", "同系列"]


def classify(query: str) -> dict:
    """
    返回 {
        "intent": "factual" | "recommend" | "relation",
        "raw_query": str,
        "hints": {            # 给 retriever 的辅助信息
            "want_relation_type": None | "same_va" | "same_series" | "same_studio",
            "tags": [],       # 提到的粗粒度标签
        }
    }
    """
    q_lower = query.lower()

    # 优先级：relation > recommend > opinion > chat > factual
    # 先判断 relation（最具体）
    for pat in RELATION_PATTERNS:
        if re.search(pat, q_lower):
            intent = "relation"
            break
    else:
        # 再判断 recommend
        for pat in RECOMMEND_PATTERNS:
            if re.search(pat, q_lower):
                intent = "recommend"
                break
        else:
            # 再判断 opinion（主观评价）
            for pat in OPINION_PATTERNS:
                if re.search(pat, q_lower):
                    intent = "opinion"
                    break
            else:
                # 再判断 chat（闲聊）
                for pat in CHAT_PATTERNS:
                    if re.search(pat, q_lower):
                        intent = "chat"
                        break
                else:
                    intent = "factual"

    # 细分 relation 类型
    want_rel = None
    if intent == "relation":
        # 声优判断：含声优关键词 OR 「名字+配过」结构
        va_by_kw  = any(k in q_lower for k in VOICE_ACTOR_KW)
        va_by_pat = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]{2,8}(配过|出演过)", query))
        if va_by_kw or va_by_pat:
            want_rel = "same_va"
        elif any(k in q_lower for k in SERIES_KW):
            want_rel = "same_series"
        elif any(k in q_lower for k in STUDIO_KW):
            want_rel = "same_studio"

    return {
        "intent":    intent,
        "raw_query": query,
        "hints": {
            "want_relation_type": want_rel,
            "tags": [],
        },
    }


if __name__ == "__main__":
    tests = [
        "Code Geass 讲什么故事？",
        "推荐几部和进击的巨人类似的番",
        "花澤香菜配过哪些角色？",
        "有哪些京阿尼制作的动画？",
        "鬼灭之刃总共几集",
        "我想看轻松治愈系的番",
        "CLANNAD 和它的续集是什么关系",
        "跟 Code Geass 同系列的作品",
        "推荐一些悬疑烧脑的动画",
        "进击的巨人第一季首播时间",
    ]
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    items = [q] if q else tests
    for item in items:
        result = classify(item)
        print(f"[{result['intent']:9s}] {item}")
        if result["hints"]["want_relation_type"]:
            print(f"           └─ relation_type: {result['hints']['want_relation_type']}")
