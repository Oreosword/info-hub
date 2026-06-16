import pytest

from deepseek_client import DeepSeekError, parse_json_content


def test_parse_json_content_accepts_markdown_json_block():
    payload = parse_json_content('```json\n{"event_title": "OpenAI 发布新模型", "total_score": 80}\n```')

    assert payload["event_title"] == "OpenAI 发布新模型"
    assert payload["total_score"] == 80


def test_parse_json_content_rejects_truncated_json():
    with pytest.raises(DeepSeekError):
        parse_json_content('{"event_title": "OpenAI 发布新模型"')
