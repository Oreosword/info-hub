from pathlib import Path
from typing import Optional

import daily_renderer
import database as db


def item_to_dict(item: db.FeedItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "summary": item.summary,
        "url": item.url,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "published_at": item.published_at,
        "fetched_at": item.fetched_at,
        "ai_summary": item.ai_summary,
        "is_read": item.is_read,
        "is_starred": item.is_starred,
    }


def source_to_dict(source: db.FeedSource, profile: Optional[db.SourceProfile] = None) -> dict:
    data = {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "config": source.config,
        "description": source.description,
        "interval_minutes": source.interval_minutes,
        "enabled": source.enabled,
        "created_at": source.created_at,
    }
    if profile:
        data["profile"] = profile_to_dict(profile)
    return data


def profile_to_dict(profile: db.SourceProfile) -> dict:
    return {
        "id": profile.id,
        "source_id": profile.source_id,
        "name": profile.name,
        "source_type": profile.source_type,
        "credibility": profile.credibility,
        "default_category": profile.default_category,
        "use_for_daily": profile.use_for_daily,
        "collection_method": profile.collection_method,
    }


def deepseek_settings_to_dict(settings: db.DeepSeekSettings) -> dict:
    return {
        "base_url": settings.base_url,
        "analysis_model": settings.analysis_model,
        "draft_model": settings.draft_model,
        "enabled": settings.enabled,
        "has_api_key": bool(settings.api_key),
        "api_key_masked": db.mask_api_key(settings.api_key),
        "updated_at": settings.updated_at,
        "key_storage": "本机 SQLite 明文保存",
    }


def candidate_to_dict(candidate: Optional[db.CandidateItem]) -> dict:
    if not candidate:
        return {}
    return {
        "id": candidate.id,
        "title": candidate.title,
        "normalized_title": candidate.normalized_title,
        "summary": candidate.summary,
        "content": candidate.content,
        "url": candidate.url,
        "canonical_url": candidate.canonical_url,
        "source_id": candidate.source_id,
        "source_profile_id": candidate.source_profile_id,
        "source_name": candidate.source_name,
        "source_type": candidate.source_type,
        "published_at": candidate.published_at,
        "collected_at": candidate.collected_at,
        "media_urls": candidate.media_urls,
        "status": candidate.status,
        "cluster_id": candidate.cluster_id,
        "ai_summary": candidate.ai_summary,
        "keywords": candidate.keywords,
        "category": candidate.category,
        "score": candidate.score,
        "score_reason": candidate.score_reason,
        "risk_flags": candidate.risk_flags,
        "dedupe_note": candidate.dedupe_note,
        "analysis_provider": candidate.analysis_provider,
        "analysis_version": candidate.analysis_version,
        "analysis_error": candidate.analysis_error,
    }


def cluster_to_dict(cluster: Optional[db.EventCluster]) -> dict:
    if not cluster:
        return {}
    return {
        "id": cluster.id,
        "event_key": cluster.event_key,
        "title": cluster.title,
        "selected_title": cluster.selected_title,
        "category": cluster.category,
        "keywords": cluster.keywords,
        "summary": cluster.summary,
        "score": cluster.score,
        "score_reason": cluster.score_reason,
        "score_breakdown": cluster.score_breakdown,
        "confidence": cluster.confidence,
        "risk_flags": cluster.risk_flags,
        "merge_reason": cluster.merge_reason,
        "status": cluster.status,
        "primary_url": cluster.primary_url,
        "sources": cluster.sources,
        "editor_note": cluster.editor_note,
        "draft_body": cluster.draft_body,
        "created_at": cluster.created_at,
        "updated_at": cluster.updated_at,
    }


def issue_to_dict(issue: Optional[db.DailyIssue]) -> dict:
    if not issue:
        return {}
    return {
        "id": issue.id,
        "issue_date": issue.issue_date,
        "issue_no": issue.issue_no,
        "title": issue.title,
        "status": issue.status,
        "markdown_path": issue.markdown_path,
        "html_path": issue.html_path,
        "assets_path": issue.assets_path,
        "html_url": daily_renderer.to_export_url(Path(issue.html_path)) if issue.html_path else "",
        "markdown_url": daily_renderer.to_export_url(Path(issue.markdown_path)) if issue.markdown_path else "",
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }
