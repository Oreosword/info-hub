"""Default feed sources configuration."""

DEFAULT_SOURCES = [
    {
        "name": "HN AI动态",
        "type": "hackernews",
        "config": {"query": "AI LLM deepseek kimi qwen Claude GPT Gemini", "tags": "story", "hits_per_page": 15},
        "description": "Hacker News 上关于 AI、大模型、DeepSeek、Kimi、Claude 等的热门讨论",
        "interval_minutes": 30,
        "enabled": True,
    },
    {
        "name": "GitHub AI热门",
        "type": "github",
        "config": {"query": "deepseek OR qwen OR kimi OR llm stars:>50", "sort": "updated", "per_page": 10},
        "description": "GitHub 上 DeepSeek、Qwen、LLM 相关的高星开源项目和最新更新",
        "interval_minutes": 60,
        "enabled": True,
    },
    {
        "name": "arXiv LLM论文",
        "type": "arxiv",
        "config": {"search_query": "cat:cs.CL OR cat:cs.AI", "max_results": 5},
        "description": "arXiv 计算语言学(cs.CL)与人工智能(cs.AI)领域的最新学术论文",
        "interval_minutes": 180,
        "enabled": True,
    },
    {
        "name": "arXiv DeepSeek相关",
        "type": "arxiv",
        "config": {"search_query": "all:deepseek OR all:qwen OR all:Claude OR all:Gemini", "max_results": 5},
        "description": "arXiv 上提及 DeepSeek、Qwen、Claude、Gemini 等模型的相关论文",
        "interval_minutes": 180,
        "enabled": True,
    },
]


def ensure_defaults() -> None:
    import database as db

    if db.get_sources():
        return
    for src in DEFAULT_SOURCES:
        db.create_source(
            name=src["name"],
            type=src["type"],
            config=src["config"],
            description=src.get("description", ""),
            interval_minutes=src["interval_minutes"],
            enabled=src["enabled"],
        )
