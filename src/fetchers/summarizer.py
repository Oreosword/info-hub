"""Generate concise Simplified Chinese summaries for feed items."""

import re
from typing import Optional

import database as db
from deepseek_client import DeepSeekClient, DeepSeekError


KNOWN_TERMS = [
    "OpenAI", "Anthropic", "Claude", "Gemini", "DeepSeek", "Kimi", "Qwen", "Llama",
    "Mistral", "Cohere", "Hugging Face", "GitHub", "Agent", "API", "SDK", "RAG",
    "LLM", "VLM", "MCP", "GPU", "NVIDIA", "Apple", "arXiv",
]

TECH_TRANSLATIONS = {
    "retrieval-augmented generation": "检索增强生成",
    "retrieval augmented generation": "检索增强生成",
    "large language model": "大语言模型",
    "large language models": "大语言模型",
    "language model": "语言模型",
    "language models": "语言模型",
    "multimodal": "多模态",
    "reasoning": "推理",
    "benchmark": "基准评测",
    "benchmarks": "基准评测",
    "framework": "框架",
    "platform": "平台",
    "open-source": "开源",
    "open source": "开源",
    "developer": "开发者",
    "developers": "开发者",
    "workflow": "工作流",
    "workflows": "工作流",
    "tool calling": "工具调用",
    "inference": "推理部署",
    "training": "训练",
    "dataset": "数据集",
    "datasets": "数据集",
    "evaluation": "评测",
    "evaluating": "评测",
    "automation": "自动化",
    "autonomous": "自主",
    "reasoning": "推理",
    "security": "安全",
    "privacy": "隐私",
    "monitoring": "监控",
    "extraction": "抽取",
    "unstructured data": "非结构化数据",
    "spatial reasoning": "空间推理",
    "agentic": "智能体式",
    "agents": "智能体",
}

FILLER_PHRASES = [
    "a leading", "an open-source", "open-source", "open source", "state-of-the-art",
    "cutting-edge", "easy-to-use", "the fastest", "fully open", "comprehensive",
]


def generate_summary(title: str, original_summary: str, source_type: str) -> str:
    """Generate a concise Chinese summary for a feed item."""
    settings = db.get_deepseek_settings()
    if settings.enabled and settings.api_key:
        result = _deepseek_summary(title, original_summary, source_type, settings)
        if result:
            return result
    return rule_chinese_summary(title, original_summary, source_type)


def needs_chinese_summary(text: str) -> bool:
    """Return true when a summary is empty or mostly non-Chinese."""
    text = (text or "").strip()
    if not text:
        return True
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    return chinese < 12 or ascii_letters > max(24, chinese * 1.35)


def rule_chinese_summary(title: str, original_summary: str, source_type: str) -> str:
    title = clean_text(title)
    source = clean_text(original_summary)
    title_terms = extract_known_terms(title)
    source_terms = extract_known_terms(source)
    terms = merge_terms(title_terms, source_terms)
    subject = best_subject(title, terms)
    phrase = english_to_chinese_phrase(source or title)

    if source_type == "github":
        if phrase:
            return compact(f"开源项目：{subject} 面向{phrase}，适合继续查看项目定位、活跃度和适用场景。", 96)
        return compact(f"GitHub 项目：{subject} 与 AI 开发相关，适合核查项目说明、更新频率和社区关注度。", 88)

    if source_type == "arxiv":
        if phrase:
            return compact(f"论文研究：{subject} 聚焦{phrase}，可作为技术与方法类线索继续复核。", 92)
        return compact(f"arXiv 论文：{subject} 与 AI 技术研究相关，建议查看摘要、方法和实验结论。", 88)

    if source_type == "hackernews":
        if phrase and phrase.lower().startswith("http"):
            phrase = ""
        topic = english_to_chinese_phrase(title) if needs_chinese_summary(title) else compact(title, 50)
        return compact(f"技术社区正在讨论 {topic}，需继续核查原始来源和社区反馈价值。", 86)

    if source_type == "rss":
        if phrase:
            return compact(f"资讯线索：{subject} 涉及{phrase}，建议优先核查官方来源与发布时间。", 90)
        return compact(f"资讯线索：{subject} 与 AI 动态相关，建议继续核查来源可信度和时效性。", 86)

    if source:
        return compact(f"资讯线索：{english_to_chinese_phrase(source) or source}", 90)
    return compact(f"资讯线索：{title}", 90)


def _deepseek_summary(title: str, original_summary: str, source_type: str, settings: db.DeepSeekSettings) -> Optional[str]:
    content = compact(clean_text(original_summary) or clean_text(title), 2600)
    prompt = (
        "请为下面 AI 资讯生成一段简体中文简介，50-90 个汉字。"
        "直接说明谁发布、提出、开源或讨论了什么，以及为什么值得看。"
        "保留必要英文专名、模型名、项目名、API、SDK、Agent 等术语。"
        "不要编造来源、数字、日期或结论，不要使用 Markdown。"
        "\n\n"
        f"来源类型：{source_type}\n标题：{title}\n内容：{content}"
    )
    try:
        response = DeepSeekClient(settings, timeout=25).chat(
            model=settings.analysis_model,
            messages=[
                {"role": "system", "content": "你是专业中文科技资讯编辑，擅长把英文 AI 资讯压缩成准确的中文简介。"},
                {"role": "user", "content": prompt},
            ],
            thinking="disabled",
            max_tokens=180,
            temperature=0.2,
        )
        return clean_model_summary(response.content)
    except DeepSeekError as exc:
        print(f"[summarizer] DeepSeek failed: {exc}")
        return None


def clean_model_summary(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"^(中文简介|简介|摘要|总结)\s*[:：]\s*", "", text)
    text = text.strip("「」“”\"'")
    return compact(text, 110)


def clean_text(text: str) -> str:
    text = text or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def english_to_chinese_phrase(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    first = re.split(r"[.!?。！？]", text, maxsplit=1)[0].strip()
    if len(first) < 12 and len(text) > len(first):
        first = text[:160]
    lowered = first.lower()
    for phrase in FILLER_PHRASES:
        lowered = lowered.replace(phrase, " ")
    topics = []
    for english, chinese in TECH_TRANSLATIONS.items():
        if english in lowered and not any(chinese in item or item in chinese for item in topics):
            topics.append(chinese)
    for term in extract_known_terms(first):
        if term == "Agent" and any("智能体" in item for item in topics):
            continue
        if term not in topics:
            topics.append(term)
    if topics:
        return join_topics(topics[:5])
    chinese = re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9 ]{2,24}", first)
    if chinese:
        return compact(chinese[0], 36)
    words = [
        w for w in re.findall(r"[A-Za-z][A-Za-z0-9+-]{2,}", first)
        if w.lower() not in {"the", "and", "for", "with", "that", "this", "from", "into", "your", "our"}
    ]
    if words:
        return "、".join(words[:4]) + " 相关能力"
    return compact(first, 36)


def extract_known_terms(text: str) -> list:
    found = []
    lowered = (text or "").lower()
    for term in KNOWN_TERMS:
        if term.lower() in lowered and term not in found:
            found.append(term)
    project = re.search(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b", text or "")
    if project and project.group(0) not in found:
        found.insert(0, project.group(0))
    return found[:8]


def best_subject(title: str, terms: list) -> str:
    if terms:
        return terms[0]
    project = re.search(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b", title or "")
    if project:
        return project.group(0)
    cleaned = re.sub(r"[\[\]【】#｜|].*$", "", title or "").strip()
    return compact(cleaned, 42) or "这条资讯"


def merge_terms(*groups) -> list:
    result = []
    for group in groups:
        for term in group:
            if term and term not in result:
                result.append(term)
    return result


def join_topics(topics: list) -> str:
    if len(topics) == 1:
        return topics[0]
    return "、".join(topics[:-1]) + f"和{topics[-1]}"


def compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
