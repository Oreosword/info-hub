import database as db
from routers.serializers import deepseek_settings_to_dict


def test_deepseek_settings_serializer_masks_api_key():
    settings = db.DeepSeekSettings(
        api_key="sk-test-1234567890",
        base_url="https://api.deepseek.com",
        analysis_model="deepseek-v4-flash",
        draft_model="deepseek-v4-pro",
        enabled=True,
        updated_at="2026-06-15T00:00:00",
    )

    payload = deepseek_settings_to_dict(settings)

    assert payload["has_api_key"] is True
    assert payload["api_key_masked"] == "sk-t...7890"
    assert "api_key" not in payload
