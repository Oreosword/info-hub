import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import database as db
from deepseek_client import DeepSeekClient, DeepSeekError, parse_json_content
from fetchers.summarizer import needs_chinese_summary, rule_chinese_summary


MODEL_TERMS = [
    "GPT", "Claude", "Gemini", "DeepSeek", "Kimi", "Qwen", "Llama", "Gemma",
    "Mistral", "Cohere", "Anthropic", "OpenAI", "Hunyuan", "MiniMax", "Agent",
    "LLM", "VLM", "MoE", "API", "MCP", "Codex", "Hugging Face", "LangChain",
]

CATEGORY_RULES = [
    ("前瞻与传闻", ["消息称", "传闻", "爆料", "曝光", "泄露", "未发布", "rumor", "leak", "unreleased"]),
    ("行业动态", ["融资", "收购", "监管", "政策", "政府", "合作", "投资", "估值", "诉讼", "安全新规"]),
    ("模型发布", ["模型", "权重", "参数", "开源", "发布", "推出", "上线", "多模态", "推理", "基准"]),
    ("开发生态", ["api", "sdk", "github", "框架", "工具", "插件", "开发者", "mcp", "codex", "agent", "dashboard"]),
    ("产品应用", ["产品", "应用", "app", "beta", "会员", "订阅", "功能", "客户端", "工作台"]),
    ("技术与洞察", ["论文", "研究", "arxiv", "benchmark", "评测", "安全", "方法", "架构", "数据集"]),
]

LOW_VALUE_TERMS = ["教程", "体验", "提示词", "合集", "转载", "广告", "课程", "入门", "清单", "榜单"]
HIGH_VALUE_TERMS = ["发布", "开源", "上线", "融资", "政策", "突破", "官方", "权重", "API", "模型", "安全"]
RUMOR_TERMS = ["消息称", "传闻", "爆料", "曝光", "leak", "rumor", "reportedly"]


@dataclass
class CandidateContext:
    title: str
    normalized_title: str
    summary: str
    content: str
    url: str
    canonical_url: str
    source_name: str
    source_type: str
    credibility: int


class DailyAI:
    provider = "rule"
    version = "rule-v2"

    def summarize(self, ctx: CandidateContext) -> str:
        raise NotImplementedError

    def extract_keywords(self, ctx: CandidateContext) -> List[str]:
        raise NotImplementedError

    def score_news_value(self, ctx: CandidateContext, category: str) -> tuple:
        raise NotImplementedError

    def draft_article(self, ctx: CandidateContext, summary: str) -> str:
        raise NotImplementedError

    def analyze_candidate(self, candidate: db.CandidateItem, profile: db.SourceProfile) -> dict:
        ctx = build_context(candidate, profile)
        category = classify_category(ctx)
        keywords = self.extract_keywords(ctx)
        summary = self.summarize(ctx)
        score, score_reason, risk_flags, score_breakdown, confidence = self.score_news_value(ctx, category)
        event_title = db.normalize_news_title(ctx.normalized_title or ctx.title)
        event_key = db.make_event_key(category, event_title, keywords, ctx.canonical_url)
        return {
            "event_key": event_key,
            "event_title": event_title,
            "canonical_url": ctx.canonical_url,
            "category": category,
            "keywords": keywords,
            "summary": summary,
            "score": score,
            "score_reason": score_reason,
            "score_breakdown": score_breakdown,
            "confidence": confidence,
            "risk_flags": risk_flags,
            "merge_reason": "规则：规范化链接、标题相似度与关键词重合",
            "recommended_status": "candidate" if score >= 55 and "传闻风险" not in risk_flags else "pending",
            "draft_body": self.draft_article(ctx, summary),
            "analysis_provider": self.provider,
            "analysis_version": self.version,
            "analysis_error": "",
        }

    def draft_issue_articles(self, issue: db.DailyIssue, clusters: List[db.EventCluster]) -> Dict[int, dict]:
        return {
            cluster.id: {
                "body": cluster.draft_body or cluster.summary or (cluster.selected_title or cluster.title),
                "provider": "rule",
                "model": "",
                "error": "",
            }
            for cluster in clusters
        }


class RuleBasedDailyAI(DailyAI):
    provider = "rule"
    version = "rule-v2"

    def summarize(self, ctx: CandidateContext) -> str:
        source = (ctx.summary or ctx.content or ctx.title).strip()
        if needs_chinese_summary(source):
            return rule_chinese_summary(ctx.title, source, ctx.source_type)
        source = strip_markdown(source)
        if not source:
            return ctx.title[:80]
        first_sentence = re.split(r"[。！？!?\n]", source, maxsplit=1)[0].strip()
        if len(first_sentence) < 18 and len(source) > len(first_sentence):
            first_sentence = source[:90]
        return compact(first_sentence, 90)

    def extract_keywords(self, ctx: CandidateContext) -> List[str]:
        text = f"{ctx.title} {ctx.summary} {ctx.content}"
        found: List[str] = []
        lowered = text.lower()
        for term in MODEL_TERMS:
            if term.lower() in lowered and term not in found:
                found.append(term)
        ascii_tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9._+-]{2,}\b", text)
        for token in ascii_tokens:
            normalized = token.strip(".,:;()[]{}")
            if normalized and normalized not in found and len(normalized) <= 32:
                found.append(normalized)
        chinese_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9.-]{3,18}", ctx.title)
        for term in chinese_terms:
            if term not in found and not any(term in c for c in db.CATEGORIES):
                found.append(term)
        return found[:10]

    def score_news_value(self, ctx: CandidateContext, category: str) -> tuple:
        text = f"{ctx.title} {ctx.summary} {ctx.content}"
        lowered = text.lower()
        ai_relevance = 20 if any(term.lower() in lowered for term in MODEL_TERMS) else 8
        authority = min(18, int(ctx.credibility / 100 * 18))
        freshness = 14
        impact = 8
        completeness = 12 if (ctx.summary or ctx.content) and ctx.url else 6
        duplicate_risk = 8
        rumor_penalty = 0
        reasons = [f"来源可信度 {ctx.credibility}"]
        risks: List[str] = []

        high_hits = [term for term in HIGH_VALUE_TERMS if term.lower() in lowered]
        if high_hits:
            impact += min(16, len(high_hits) * 4)
            reasons.append("包含发布、开源、政策、模型等高价值线索")

        low_hits = [term for term in LOW_VALUE_TERMS if term in text]
        if low_hits:
            impact -= min(16, len(low_hits) * 5)
            completeness -= 2
            reasons.append("存在教程、合集、广告或低日报价值信号")

        if category == "前瞻与传闻" or any(term in lowered for term in RUMOR_TERMS):
            rumor_penalty = -10
            risks.append("传闻风险")
            reasons.append("含未确认或社区爆料表述")
        if ctx.source_type == "hackernews":
            risks.append("社区讨论，需复核原始来源")
            authority -= 2
        if not ctx.url:
            risks.append("缺少来源链接")
            completeness -= 4
        if any(term in lowered for term in ["official", "release", "blog", "arxiv", "github", "官网", "官方"]):
            authority += 4
            reasons.append("含官方或一手来源线索")

        score_breakdown = {
            "AI相关性": clamp(ai_relevance, 0, 20),
            "来源权威性": clamp(authority, 0, 22),
            "新鲜度": clamp(freshness, 0, 15),
            "影响力": clamp(impact, 0, 22),
            "信息完整度": clamp(completeness, 0, 14),
            "重复风险": clamp(duplicate_risk, 0, 10),
            "传闻风险": rumor_penalty,
        }
        score = clamp(sum(int(v) for v in score_breakdown.values()), 0, 100)
        confidence = 45 if risks else 60
        return score, "；".join(reasons), risks, score_breakdown, confidence

    def draft_article(self, ctx: CandidateContext, summary: str) -> str:
        body = strip_markdown(ctx.content or ctx.summary)
        if not body:
            body = summary
        body = compact(body, 520)
        if body == summary:
            return summary
        return f"{summary}\n\n{body}"


class DeepSeekDailyAI(DailyAI):
    provider = "deepseek"
    version = "deepseek-v1"

    def __init__(self, settings: db.DeepSeekSettings):
        self.settings = settings
        self.client = DeepSeekClient(settings)
        self.fallback = RuleBasedDailyAI()

    def analyze_candidate(self, candidate: db.CandidateItem, profile: db.SourceProfile) -> dict:
        ctx = build_context(candidate, profile)
        try:
            response = self.client.chat(
                model=self.settings.analysis_model,
                messages=[
                    {"role": "system", "content": analysis_system_prompt()},
                    {"role": "user", "content": analysis_user_prompt(ctx)},
                ],
                response_json=True,
                thinking="disabled",
                max_tokens=1800,
                temperature=0.1,
            )
            data = parse_json_content(response.content)
            return normalize_deepseek_analysis(data, ctx, response.model)
        except Exception as exc:
            analysis = self.fallback.analyze_candidate(candidate, profile)
            analysis["analysis_error"] = str(exc)
            analysis["score_reason"] = f"{analysis['score_reason']}；DeepSeek 降级：{exc}"
            return analysis

    def summarize(self, ctx: CandidateContext) -> str:
        return self.fallback.summarize(ctx)

    def extract_keywords(self, ctx: CandidateContext) -> List[str]:
        return self.fallback.extract_keywords(ctx)

    def score_news_value(self, ctx: CandidateContext, category: str) -> tuple:
        return self.fallback.score_news_value(ctx, category)

    def draft_article(self, ctx: CandidateContext, summary: str) -> str:
        return self.fallback.draft_article(ctx, summary)

    def draft_issue_articles(self, issue: db.DailyIssue, clusters: List[db.EventCluster]) -> Dict[int, dict]:
        fallback = self.fallback.draft_issue_articles(issue, clusters)
        if not clusters:
            return fallback

        result: Dict[int, dict] = {}
        for chunk in chunked(clusters, 8):
            try:
                response = self.client.chat(
                    model=self.settings.draft_model,
                    messages=[
                        {"role": "system", "content": draft_system_prompt()},
                        {"role": "user", "content": draft_user_prompt(issue, chunk)},
                    ],
                    response_json=True,
                    thinking="enabled",
                    reasoning_effort="high",
                    max_tokens=min(6000, 900 * max(1, len(chunk))),
                    temperature=0.25,
                )
                data = parse_json_content(response.content)
                result.update(normalize_draft_response(data, chunk, response.model))
            except Exception as exc:
                for cluster in chunk:
                    fallback_item = fallback[cluster.id]
                    fallback_item["error"] = str(exc)
                    result[cluster.id] = fallback_item

        for cluster in clusters:
            result.setdefault(cluster.id, fallback[cluster.id])
        return result


def get_daily_ai() -> DailyAI:
    settings = db.get_deepseek_settings()
    if settings.enabled and settings.api_key:
        return DeepSeekDailyAI(settings)
    return RuleBasedDailyAI()


def build_context(candidate: db.CandidateItem, profile: db.SourceProfile) -> CandidateContext:
    return CandidateContext(
        title=candidate.title,
        normalized_title=candidate.normalized_title or db.normalize_news_title(candidate.title),
        summary=candidate.summary,
        content=candidate.content,
        url=candidate.url,
        canonical_url=candidate.canonical_url or db.canonicalize_url(candidate.url),
        source_name=candidate.source_name,
        source_type=candidate.source_type,
        credibility=profile.credibility,
    )


def analysis_system_prompt() -> str:
    categories = "、".join(db.CATEGORIES)
    return (
        "你是一个严谨的 AI 资讯日报编辑。你的任务是把原始候选资讯转成可人工复核的日报事件。"
        "只根据输入内容判断，不要编造来源、数字或结论。"
        "必须输出一个 JSON object，不要输出 Markdown。"
        f"category 只能从这些栏目中选择：{categories}。"
        "传闻、社区爆料、未官方确认内容必须放入 risk_flags，不要自动推荐入选。"
    )


def analysis_user_prompt(ctx: CandidateContext) -> str:
    return f"""
请分析这条 AI 资讯候选，并输出固定 JSON：
{{
  "event_title": "适合日报展示的事件标题，不超过 60 字",
  "category": "要闻/模型发布/开发生态/产品应用/技术与洞察/行业动态/前瞻与传闻",
  "summary_50": "50 字左右摘要",
  "keywords": ["3-8 个关键词"],
  "entities": ["公司、模型、产品、项目、人物等实体"],
  "score_breakdown": {{
    "AI相关性": 0-20,
    "来源权威性": 0-20,
    "新鲜度": 0-15,
    "影响力": 0-20,
    "信息完整度": 0-15,
    "重复风险": 0-10,
    "传闻风险": -15 到 0
  }},
  "total_score": 0-100,
  "confidence": 0-100,
  "risk_flags": ["风险标签，没有则空数组"],
  "is_duplicate_hint": false,
  "merge_reason": "用于解释为什么可能与同事件合并",
  "recommended_status": "candidate/pending/ignored",
  "draft_body": "日报正文草稿，150-300 字；传闻必须保留未确认表述"
}}

标题：{ctx.title}
规范标题：{ctx.normalized_title}
链接：{ctx.url}
规范链接：{ctx.canonical_url}
来源：{ctx.source_name}（{ctx.source_type}，可信度 {ctx.credibility}/100）
摘要：{compact(ctx.summary, 1200)}
正文摘录：{compact(ctx.content, 2600)}
""".strip()


def draft_system_prompt() -> str:
    return (
        "你是 AI 日报成稿编辑。请把已入选事件写成可发布前复核的中文日报正文。"
        "只允许使用输入里的标题、摘要、草稿、风险标签和来源证据，不要编造来源、数字、融资额、发布日期或结论。"
        "传闻、社区讨论、未官方确认的内容必须保留“消息称/社区讨论/尚未官方确认”等限定表达。"
        "每篇正文 120-260 字，先讲事实，再讲影响或需要复核的点。"
        "必须输出 JSON object，格式为：{\"articles\":[{\"cluster_id\":1,\"body\":\"正文\"}]}。"
    )


def draft_user_prompt(issue: db.DailyIssue, clusters: List[db.EventCluster]) -> str:
    entries = []
    for cluster in clusters:
        entries.append(
            {
                "cluster_id": cluster.id,
                "title": cluster.selected_title or cluster.title,
                "category": cluster.category,
                "summary": compact(cluster.summary, 360),
                "current_draft": compact(cluster.draft_body, 900),
                "score": cluster.score,
                "risk_flags": cluster.risk_flags,
                "sources": [
                    {
                        "source_name": source.get("source_name", ""),
                        "title": source.get("title", ""),
                        "url": source.get("url", ""),
                    }
                    for source in (cluster.sources or [])[:6]
                ],
            }
        )
    return (
        f"日报日期：{issue.issue_date}\n"
        f"期号：{issue.issue_no}\n"
        "请为以下入选事件生成正文。输出 JSON，不要 Markdown。\n"
        + json.dumps({"events": entries}, ensure_ascii=False, indent=2)
    )


def normalize_deepseek_analysis(data: Dict[str, Any], ctx: CandidateContext, model: str) -> dict:
    event_title = db.normalize_news_title(str(data.get("event_title") or ctx.normalized_title or ctx.title))
    category = db.normalize_category(str(data.get("category") or classify_category(ctx)))
    keywords = normalize_string_list(data.get("keywords"))[:10]
    entities = normalize_string_list(data.get("entities"))[:8]
    for entity in entities:
        if entity not in keywords:
            keywords.append(entity)
    summary = compact(str(data.get("summary_50") or data.get("summary") or ctx.summary or ctx.title), 120)
    score_breakdown = normalize_score_breakdown(data.get("score_breakdown"))
    score = data.get("total_score")
    if score is None:
        score = sum(int(v) for v in score_breakdown.values())
    score = clamp(int(score), 0, 100)
    confidence = clamp(int(data.get("confidence") or 65), 0, 100)
    risk_flags = normalize_string_list(data.get("risk_flags"))
    if category == "前瞻与传闻" and "传闻风险" not in risk_flags:
        risk_flags.append("传闻风险")
    recommended_status = str(data.get("recommended_status") or "")
    event_key = db.make_event_key(category, event_title, keywords, ctx.canonical_url)
    score_reason = score_reason_from_breakdown(score_breakdown, risk_flags)
    return {
        "event_key": event_key,
        "event_title": event_title,
        "canonical_url": ctx.canonical_url,
        "category": category,
        "keywords": keywords[:10],
        "summary": summary,
        "score": score,
        "score_reason": score_reason,
        "score_breakdown": score_breakdown,
        "confidence": confidence,
        "risk_flags": risk_flags[:8],
        "merge_reason": str(data.get("merge_reason") or "DeepSeek：按事件标题、实体和规范链接判断"),
        "recommended_status": recommended_status,
        "draft_body": compact(str(data.get("draft_body") or summary), 900),
        "analysis_provider": "deepseek",
        "analysis_version": f"deepseek-v1:{model}",
        "analysis_error": "",
    }


def normalize_draft_response(data: Dict[str, Any], clusters: List[db.EventCluster], model: str) -> Dict[int, dict]:
    by_id = {cluster.id: cluster for cluster in clusters}
    result: Dict[int, dict] = {}
    articles = data.get("articles") if isinstance(data, dict) else None
    if not isinstance(articles, list):
        articles = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        try:
            cluster_id = int(item.get("cluster_id"))
        except (TypeError, ValueError):
            continue
        if cluster_id not in by_id:
            continue
        body = compact(str(item.get("body") or ""), 1200)
        if not body:
            continue
        result[cluster_id] = {
            "body": body,
            "provider": "deepseek",
            "model": model,
            "error": "",
        }
    for cluster in clusters:
        if cluster.id not in result:
            result[cluster.id] = {
                "body": cluster.draft_body or cluster.summary or (cluster.selected_title or cluster.title),
                "provider": "rule",
                "model": "",
                "error": "DeepSeek 未返回该事件正文",
            }
    return result


def normalize_score_breakdown(value: Any) -> Dict[str, int]:
    defaults = {
        "AI相关性": 10,
        "来源权威性": 10,
        "新鲜度": 8,
        "影响力": 8,
        "信息完整度": 8,
        "重复风险": 5,
        "传闻风险": 0,
    }
    if not isinstance(value, dict):
        return defaults
    result = {}
    for key, default in defaults.items():
        try:
            result[key] = int(value.get(key, default))
        except (TypeError, ValueError):
            result[key] = default
    result["传闻风险"] = clamp(result["传闻风险"], -15, 0)
    for key in ("AI相关性", "来源权威性", "影响力"):
        result[key] = clamp(result[key], 0, 20)
    for key in ("新鲜度", "信息完整度"):
        result[key] = clamp(result[key], 0, 15)
    result["重复风险"] = clamp(result["重复风险"], 0, 10)
    return result


def normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        raw = re.split(r"[,，、\n]", value)
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    result = []
    for item in raw:
        text = str(item).strip()
        if text and text not in result:
            result.append(text[:32])
    return result


def chunked(items: List[Any], size: int) -> List[List[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def score_reason_from_breakdown(score_breakdown: Dict[str, int], risk_flags: List[str]) -> str:
    strongest = sorted(score_breakdown.items(), key=lambda item: item[1], reverse=True)[:3]
    reason = "；".join(f"{key} {value}" for key, value in strongest)
    if risk_flags:
        reason += "；风险：" + "、".join(risk_flags)
    return reason


def classify_category(ctx: CandidateContext) -> str:
    text = f"{ctx.title} {ctx.summary} {ctx.content}".lower()
    for category, terms in CATEGORY_RULES:
        if any(term.lower() in text for term in terms):
            return category
    if ctx.source_type == "github":
        return "开发生态"
    if ctx.source_type == "arxiv":
        return "技术与洞察"
    if ctx.source_type == "hackernews":
        return "前瞻与传闻"
    return "技术与洞察"


def strip_markdown(text: str) -> str:
    text = text or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*_>#-]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
