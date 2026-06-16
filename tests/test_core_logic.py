from core_logic import (
    CATEGORIES,
    canonicalize_url,
    compute_content_hash,
    normalize_category,
    normalize_news_title,
    normalize_recommended_status,
)


def test_canonicalize_url_removes_tracking_fragment_and_sorts_query():
    url = "https://Example.com/path/?utm_source=newsletter&b=2&a=1#section"

    assert canonicalize_url(url) == "https://example.com/path?a=1&b=2"


def test_canonicalize_url_strips_common_tracking_params():
    url = "https://example.com/a/?ref=hn&utm_medium=social&fbclid=abc"

    assert canonicalize_url(url) == "https://example.com/a"


def test_compute_content_hash_is_stable_for_normalized_content():
    first = compute_content_hash("  OpenAI 发布 API  ", "https://example.com/?utm_source=x", "摘要", "正文")
    second = compute_content_hash("OpenAI 发布 API", "https://example.com/", "摘要", "正文")

    assert first == second


def test_category_and_status_normalization_keep_known_values_safe():
    assert normalize_category("模型发布") == "模型发布"
    assert normalize_category("unknown") == "技术与洞察"
    assert CATEGORIES[0] == "要闻"
    assert normalize_recommended_status("selected", 30, []) == "pending"
    assert normalize_recommended_status(None, 70, []) == "candidate"
    assert normalize_recommended_status(None, 70, ["传闻风险"]) == "pending"


def test_normalize_news_title_removes_noise_but_keeps_project_names():
    assert normalize_news_title("  GitHub - openai/codex: AI coding agent  ") == "openai/codex: AI coding agent"
