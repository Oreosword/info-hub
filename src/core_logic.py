"""Pure business rules shared by storage, workflow, and tests."""

import hashlib
import re
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


CATEGORIES = ["要闻", "模型发布", "开发生态", "产品应用", "技术与洞察", "行业动态", "前瞻与传闻"]
CLUSTER_STATUSES = {"pending", "ignored", "candidate", "selected", "drafted"}
PROTECTED_CLUSTER_STATUSES = {"selected", "ignored", "drafted"}


def normalize_category(category: Optional[str]) -> str:
    return category if category in CATEGORIES else "技术与洞察"


def normalize_news_title(title: str) -> str:
    value = re.sub(r"\s+", " ", title or "").strip()
    value = re.sub(r"^GitHub\s*-\s*", "", value, flags=re.I)
    value = re.sub(r"^[#【\[\(（\s]*\d{1,3}[\.、\)\]】）\s-]+", "", value)
    value = re.sub(r"[\s|｜-]+(机器之心|量子位|爱范儿|少数派|The Decoder|TechCrunch|VentureBeat)$", "", value, flags=re.I)
    return value[:160]


def canonicalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    ignored_prefixes = ("utm_",)
    ignored_names = {
        "spm",
        "from",
        "share",
        "share_token",
        "ref",
        "ref_src",
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
    }
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith(ignored_prefixes) and k.lower() not in ignored_names
    ]
    normalized_path = re.sub(r"/+$", "", parsed.path or "/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            urlencode(sorted(query), doseq=True),
            "",
        )
    )


def normalize_text(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)
    return value[:120]


def compute_content_hash(title: str, url: str = "", summary: str = "", content: str = "") -> str:
    canonical = canonicalize_url(url)
    if canonical:
        seed = "url:" + canonical
    else:
        seed = "text:" + normalize_text(title + summary + content)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def make_event_key(category: str, title: str, keywords: List[str], canonical_url: str = "") -> str:
    if canonical_url:
        return compute_content_hash("", canonical_url)[:24]
    seed_terms = [normalize_text(k) for k in keywords[:5] if normalize_text(k)]
    seed = f"{category}:{normalize_text(title)}:{'|'.join(seed_terms[:4])}"
    return compute_content_hash(seed)[:24]


def normalize_recommended_status(status: Optional[str], score: int, risk_flags: List[str]) -> str:
    value = (status or "").strip().lower()
    mapping = {
        "ignore": "ignored",
        "ignored": "ignored",
        "pending": "pending",
        "candidate": "candidate",
        "候选": "candidate",
        "忽略": "ignored",
        "待判断": "pending",
    }
    if value in mapping:
        normalized = mapping[value]
    elif score >= 55:
        normalized = "candidate"
    else:
        normalized = "pending"
    if normalized == "ignored" and score >= 55:
        normalized = "candidate"
    if normalized == "candidate" and ("传闻" in "".join(risk_flags) or score < 45):
        normalized = "pending"
    return normalized


def tokenize_for_similarity(text: str) -> set:
    stop_words = {"发布", "推出", "上线", "测试", "验证"}
    tokens = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9._+-]{1,}|[\u4e00-\u9fff]{2,}", text or ""):
        normalized = normalize_text(token)
        if normalized and normalized not in stop_words:
            tokens.add(normalized)
    return tokens
