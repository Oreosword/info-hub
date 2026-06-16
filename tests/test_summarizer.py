from fetchers.summarizer import needs_chinese_summary, rule_chinese_summary


def test_rule_summary_translates_github_description_to_chinese_style():
    summary = rule_chinese_summary(
        "ragflow",
        "An open-source retrieval-augmented generation engine for developers.",
        "github",
    )

    assert "开源项目" in summary
    assert "检索增强生成" in summary
    assert needs_chinese_summary(summary) is False
