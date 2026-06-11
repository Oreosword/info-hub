import html
import json
from pathlib import Path
from typing import Dict, List

import ai_workflow
import database as db


def export_issue(issue_id: int) -> Dict[str, object]:
    issue = db.get_issue(issue_id)
    if not issue:
        raise ValueError("Issue not found")

    clusters = db.get_issue_clusters(issue.id)
    if not clusters:
        clusters = db.get_clusters(selected_only=True, limit=80)

    export_dir = db.EXPORT_ROOT / issue.issue_date
    export_dir.mkdir(parents=True, exist_ok=True)

    article_drafts = ai_workflow.get_daily_ai().draft_issue_articles(issue, clusters)
    markdown = render_markdown(issue, clusters, article_drafts)
    html_text = render_html(issue, clusters, article_drafts)
    assets = collect_assets(clusters)

    md_path = export_dir / "daily.md"
    html_path = export_dir / "daily.html"
    assets_path = export_dir / "assets.json"

    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    assets_path.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")
    db.save_issue_exports(issue.id, str(md_path), str(html_path), str(assets_path))

    stats = draft_stats(article_drafts)
    return {
        "markdown_path": str(md_path),
        "html_path": str(html_path),
        "assets_path": str(assets_path),
        "html_url": to_export_url(html_path),
        "markdown_url": to_export_url(md_path),
        "assets_url": to_export_url(assets_path),
        "draft_provider": stats["provider"],
        "draft_models": stats["models"],
        "draft_errors": stats["errors"],
    }


def to_export_url(path: Path) -> str:
    rel = path.relative_to(db.ROOT_DIR).as_posix()
    return "/" + rel


def group_clusters(clusters: List[db.EventCluster]) -> Dict[str, List[db.EventCluster]]:
    grouped: Dict[str, List[db.EventCluster]] = {category: [] for category in db.CATEGORIES}
    for cluster in clusters:
        grouped.setdefault(db.normalize_category(cluster.category), []).append(cluster)
    return grouped


def render_markdown(issue: db.DailyIssue, clusters: List[db.EventCluster], article_drafts: Dict[int, dict]) -> str:
    grouped = group_clusters(clusters)
    lines = [
        f"# {issue.title}",
        "",
        f"> 第 {issue.issue_no} 期。内容由 AI 辅助整理，最终发布前请人工复核来源、事实和措辞。",
        "",
        "## 今日概览",
        "",
    ]
    index = 1
    article_numbers: Dict[int, int] = {}
    for category in db.CATEGORIES:
        items = grouped.get(category, [])
        if not items:
            continue
        lines.append(f"### {category}（{len(items)}）")
        for cluster in items:
            article_numbers[cluster.id] = index
            title = cluster.selected_title or cluster.title
            url = cluster.primary_url or first_source_url(cluster)
            link = f"[{title}]({url})" if url else title
            lines.append(f"- #{index} {link}")
            index += 1
        lines.append("")

    if not clusters:
        lines.extend(["暂无入选内容。", ""])

    lines.append("---")
    lines.append("")
    for cluster in clusters:
        number = article_numbers.get(cluster.id, 0)
        title = cluster.selected_title or cluster.title
        lines.append(f"## {title} `#{number}`")
        lines.append("")
        if cluster.summary:
            lines.append(f"> {cluster.summary}")
            lines.append("")
        body = get_article_body(cluster, article_drafts)
        for paragraph in split_paragraphs(body):
            lines.append(paragraph)
            lines.append("")
        urls = cluster_links(cluster)
        if urls:
            lines.append("相关链接：")
            for url in urls:
                lines.append(f"- {url}")
            lines.append("")
        media = cluster_media(cluster)
        if media:
            lines.append("媒体素材：")
            for url in media:
                lines.append(f"- {url}")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("提示：内容由 AI 辅助创作，可能存在幻觉和错误。")
    return "\n".join(lines).strip() + "\n"


def render_html(issue: db.DailyIssue, clusters: List[db.EventCluster], article_drafts: Dict[int, dict]) -> str:
    grouped = group_clusters(clusters)
    article_numbers: Dict[int, int] = {}
    counter = 1
    for category in db.CATEGORIES:
        for cluster in grouped.get(category, []):
            article_numbers[cluster.id] = counter
            counter += 1

    overview_parts = []
    for category in db.CATEGORIES:
        items = grouped.get(category, [])
        if not items:
            continue
        rows = []
        for cluster in items:
            number = article_numbers[cluster.id]
            title = html.escape(cluster.selected_title or cluster.title)
            url = html.escape(cluster.primary_url or first_source_url(cluster))
            link = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title
            rows.append(f'<li><a class="item-no" href="#article-{number}">#{number}</a>{link}</li>')
        overview_parts.append(
            f"""
            <section class="overview-section">
              <h3>{html.escape(category)} <span>{len(items)}</span></h3>
              <ul>{''.join(rows)}</ul>
            </section>
            """
        )

    article_parts = []
    for cluster in clusters:
        number = article_numbers.get(cluster.id, 0)
        title = html.escape(cluster.selected_title or cluster.title)
        summary = html.escape(cluster.summary)
        draft_meta = article_drafts.get(cluster.id, {})
        body = "".join(f"<p>{inline_markup(p)}</p>" for p in split_paragraphs(get_article_body(cluster, article_drafts)))
        links = "".join(
            f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(short_url(url))}</a>'
            for url in cluster_links(cluster)
        )
        media = "".join(
            f'<li><a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(short_url(url))}</a></li>'
            for url in cluster_media(cluster)
        )
        media_block = f'<div class="media-block"><strong>媒体素材</strong><ul>{media}</ul></div>' if media else ""
        risk = "".join(f"<span>{html.escape(flag)}</span>" for flag in cluster.risk_flags)
        risk_block = f'<div class="risk-flags">{risk}</div>' if risk else ""
        article_parts.append(
            f"""
            <article id="article-{number}" class="article">
              <div class="article-kicker">{html.escape(cluster.category)} · #{number} · 评分 {cluster.score}</div>
              <h2>{title}</h2>
              <div class="draft-meta">成稿：{html.escape(draft_label(draft_meta))}</div>
              {risk_block}
              <blockquote>{summary}</blockquote>
              <div class="article-body">{body}</div>
              <div class="related-links"><strong>相关链接</strong><div>{links or '<span>暂无链接</span>'}</div></div>
              {media_block}
            </article>
            """
        )

    empty = '<div class="empty">暂无入选内容。先在筛选台把事件标记为“入选”，再重新生成。</div>' if not clusters else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="paper">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(issue.title)}</title>
<style>
:root {{
  --bg: #f8f5ef;
  --surface: #fffdf8;
  --surface-soft: #f0ebe2;
  --border: #ded5c8;
  --text: #20242b;
  --muted: #7b786f;
  --accent: #c94b2a;
  --accent-soft: #fff0e9;
  --blue: #2d6cdf;
  --green: #2f7d4f;
  --shadow: 0 16px 60px rgba(77, 57, 38, .08);
}}
[data-theme="ink"] {{
  --bg: #111417;
  --surface: #1b2026;
  --surface-soft: #252b33;
  --border: #39414c;
  --text: #e7edf3;
  --muted: #9ca8b5;
  --accent: #f07d4f;
  --accent-soft: rgba(240,125,79,.12);
  --blue: #7db1ff;
  --green: #78c893;
  --shadow: 0 16px 60px rgba(0,0,0,.28);
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif; line-height: 1.78; }}
.progress {{ position: fixed; top: 0; left: 0; height: 3px; background: var(--accent); transform-origin: left; transform: scaleX(0); width: 100%; z-index: 20; }}
header {{ position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); }}
.header-inner {{ height: 58px; max-width: 1060px; margin: auto; padding: 0 22px; display: flex; align-items: center; gap: 16px; }}
.brand {{ font-weight: 800; font-size: 19px; margin-right: auto; }}
.head-btn {{ border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: 999px; padding: 8px 12px; cursor: pointer; }}
main {{ max-width: 1060px; margin: auto; padding: 70px 22px 96px; }}
.hero {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 28px; align-items: end; margin-bottom: 44px; }}
.month {{ color: var(--muted); text-transform: uppercase; letter-spacing: .14em; font: 700 13px system-ui, sans-serif; }}
h1 {{ font-size: clamp(46px, 9vw, 86px); line-height: 1; margin: 20px 0 12px; letter-spacing: 0; }}
.subtitle {{ color: var(--muted); font-size: 20px; }}
.issue {{ background: var(--surface-soft); border: 1px solid var(--border); border-radius: 999px; padding: 8px 14px; color: var(--muted); }}
.overview {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 28px 34px; box-shadow: var(--shadow); margin-bottom: 44px; }}
.overview h2 {{ margin: 0 0 18px; font-size: 21px; }}
.overview-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px 32px; }}
.overview-section h3 {{ color: var(--accent); font: 800 15px system-ui, sans-serif; margin: 0 0 8px; }}
.overview-section h3 span {{ display: inline-grid; place-items: center; min-width: 24px; height: 24px; margin-left: 6px; background: var(--surface-soft); border-radius: 999px; color: var(--muted); font-size: 13px; }}
.overview-section ul {{ margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; }}
.overview-section li {{ display: flex; gap: 10px; align-items: baseline; font-size: 15px; }}
a {{ color: var(--text); text-decoration-color: color-mix(in srgb, var(--accent) 40%, transparent); text-underline-offset: 3px; }}
.item-no {{ flex: none; color: var(--accent); background: var(--accent-soft); border-radius: 6px; padding: 0 6px; text-decoration: none; font: 700 13px system-ui, sans-serif; }}
.article {{ scroll-margin-top: 82px; border-top: 1px solid var(--border); padding: 34px 0; }}
.article-kicker {{ color: var(--muted); font: 700 12px system-ui, sans-serif; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }}
.article h2 {{ font-size: clamp(24px, 4vw, 34px); line-height: 1.25; margin: 0 0 16px; letter-spacing: 0; }}
.draft-meta {{ color: var(--muted); font: 12px system-ui, sans-serif; margin: -8px 0 14px; }}
blockquote {{ margin: 0 0 22px; padding: 14px 18px; border-left: 4px solid var(--accent); background: var(--accent-soft); border-radius: 0 8px 8px 0; }}
.article-body p {{ margin: 0 0 16px; }}
.related-links, .media-block {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-top: 18px; font-family: system-ui, sans-serif; font-size: 13px; }}
.related-links div {{ display: grid; gap: 7px; margin-top: 8px; }}
.media-block ul {{ margin: 8px 0 0; padding-left: 18px; }}
.risk-flags {{ display: flex; flex-wrap: wrap; gap: 8px; margin: -4px 0 16px; }}
.risk-flags span {{ border: 1px solid var(--border); color: var(--muted); border-radius: 999px; padding: 3px 9px; font: 12px system-ui, sans-serif; }}
.empty {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 24px; color: var(--muted); }}
footer {{ color: var(--muted); border-top: 1px solid var(--border); margin-top: 36px; padding-top: 24px; font-size: 14px; }}
code {{ color: var(--accent); background: var(--accent-soft); border-radius: 4px; padding: 0 4px; }}
strong {{ color: var(--accent); }}
@media (max-width: 760px) {{
  main {{ padding-top: 42px; }}
  .hero {{ grid-template-columns: 1fr; }}
  .overview {{ padding: 22px; }}
  .overview-grid {{ grid-template-columns: 1fr; }}
  .header-inner {{ padding: 0 14px; }}
}}
</style>
</head>
<body>
<div class="progress" id="progress"></div>
<header>
  <div class="header-inner">
    <div class="brand">AI 日报</div>
    <button class="head-btn" onclick="toggleTheme()">主题</button>
  </div>
</header>
<main>
  <section class="hero">
    <div>
      <div class="month">{html.escape(issue.issue_date[:7])}</div>
      <h1>{html.escape(issue.issue_date[-2:])}</h1>
      <div class="subtitle">AI 日报 {html.escape(issue.issue_date)}</div>
    </div>
    <div class="issue">第 {issue.issue_no} 期</div>
  </section>
  <section class="overview">
    <h2>今日概览</h2>
    <div class="overview-grid">{''.join(overview_parts) or '<p>暂无入选内容。</p>'}</div>
  </section>
  {empty}
  {''.join(article_parts)}
  <footer>提示：内容由 AI 辅助创作，可能存在幻觉和错误。发布前请人工核查事实、来源和图片授权。</footer>
</main>
<script>
function toggleTheme() {{
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === 'ink' ? 'paper' : 'ink';
}}
window.addEventListener('scroll', () => {{
  const doc = document.documentElement;
  const total = doc.scrollHeight - doc.clientHeight;
  const ratio = total > 0 ? doc.scrollTop / total : 0;
  document.getElementById('progress').style.transform = `scaleX(${{ratio}})`;
}}, {{ passive: true }});
</script>
</body>
</html>
"""


def collect_assets(clusters: List[db.EventCluster]) -> List[dict]:
    assets = []
    for cluster in clusters:
        for url in cluster_media(cluster):
            assets.append({"cluster_id": cluster.id, "title": cluster.selected_title or cluster.title, "url": url})
    return assets


def get_article_body(cluster: db.EventCluster, article_drafts: Dict[int, dict]) -> str:
    draft = article_drafts.get(cluster.id) or {}
    return draft.get("body") or cluster.draft_body or cluster.summary or (cluster.selected_title or cluster.title)


def draft_label(draft_meta: dict) -> str:
    provider = draft_meta.get("provider") or "rule"
    if provider == "deepseek":
        model = draft_meta.get("model") or "DeepSeek"
        return f"DeepSeek / {model}"
    if draft_meta.get("error"):
        return "规则降级"
    return "规则"


def draft_stats(article_drafts: Dict[int, dict]) -> dict:
    providers = {draft.get("provider") or "rule" for draft in article_drafts.values()}
    models = sorted({draft.get("model") for draft in article_drafts.values() if draft.get("model")})
    errors = [draft.get("error") for draft in article_drafts.values() if draft.get("error")]
    if not providers:
        provider = "none"
    elif providers == {"deepseek"}:
        provider = "deepseek"
    elif "deepseek" in providers:
        provider = "mixed"
    else:
        provider = "rule"
    return {"provider": provider, "models": models, "errors": errors[:5]}


def cluster_links(cluster: db.EventCluster) -> List[str]:
    links = []
    for source in cluster.sources:
        url = source.get("url")
        if url and url not in links:
            links.append(url)
    if cluster.primary_url and cluster.primary_url not in links:
        links.insert(0, cluster.primary_url)
    return links[:8]


def cluster_media(cluster: db.EventCluster) -> List[str]:
    urls = []
    for candidate in db.get_cluster_candidates(cluster.id):
        for url in candidate.media_urls:
            if url and url not in urls:
                urls.append(url)
    return urls[:12]


def first_source_url(cluster: db.EventCluster) -> str:
    links = cluster_links(cluster)
    return links[0] if links else ""


def split_paragraphs(text: str) -> List[str]:
    parts = [p.strip() for p in (text or "").split("\n") if p.strip()]
    if parts:
        return parts
    return [text.strip()] if text else []


def inline_markup(text: str) -> str:
    escaped = html.escape(text)
    for term in ["OpenAI", "Claude", "Gemini", "DeepSeek", "Kimi", "Qwen", "GitHub", "Hugging Face", "API", "Agent", "模型"]:
        escaped = escaped.replace(html.escape(term), f"<strong>{html.escape(term)}</strong>")
    return escaped


def short_url(url: str) -> str:
    url = url.replace("https://", "").replace("http://", "")
    return url[:90] + "…" if len(url) > 90 else url
