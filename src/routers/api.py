from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import daily_renderer
import database as db
from deepseek_client import DeepSeekClient, DeepSeekError
from routers.serializers import (
    candidate_to_dict,
    cluster_to_dict,
    deepseek_settings_to_dict,
    issue_to_dict,
    item_to_dict,
    profile_to_dict,
    source_to_dict,
)
import workflow
from scheduler import run_fetch

router = APIRouter()


class ImportCandidateRequest(BaseModel):
    title: str
    url: str = ""
    summary: str = ""
    content: str = ""
    source_name: str = "手动导入"
    published_at: Optional[str] = None
    media_urls: List[str] = Field(default_factory=list)


class ClusterUpdateRequest(BaseModel):
    status: Optional[str] = None
    selected_title: Optional[str] = None
    category: Optional[str] = None
    editor_note: Optional[str] = None
    draft_body: Optional[str] = None
    summary: Optional[str] = None


class GenerateIssueRequest(BaseModel):
    issue_date: Optional[str] = None
    cluster_ids: Optional[List[int]] = None


class DeepSeekSettingsRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    analysis_model: Optional[str] = None
    draft_model: Optional[str] = None
    enabled: Optional[bool] = None
    clear_api_key: bool = False


class AnalysisRunRequest(BaseModel):
    scope: str = "unreviewed"
    limit: int = Field(default=50, ge=1, le=500)


class RebuildClustersRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=1000)
    reanalyze: bool = False


class SummaryBackfillRequest(BaseModel):
    limit: int = Field(default=300, ge=1, le=1000)


@router.get("/items")
async def list_items(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source_id: Optional[int] = None,
    is_read: Optional[bool] = None,
    is_starred: Optional[bool] = None,
):
    items = db.get_items(limit=limit, offset=offset, source_id=source_id, is_read=is_read, is_starred=is_starred)
    return {"items": [item_to_dict(i) for i in items]}


@router.get("/items/search")
async def search_items(q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=200)):
    items = db.search_items(q, limit=limit)
    return {"items": [item_to_dict(i) for i in items]}


@router.post("/items/{item_id}/read")
async def mark_read(item_id: int):
    db.mark_read(item_id, True)
    return {"ok": True}


@router.post("/items/{item_id}/unread")
async def mark_unread(item_id: int):
    db.mark_read(item_id, False)
    return {"ok": True}


@router.post("/items/{item_id}/star")
async def star_item(item_id: int):
    db.mark_starred(item_id, True)
    return {"ok": True}


@router.post("/items/{item_id}/unstar")
async def unstar_item(item_id: int):
    db.mark_starred(item_id, False)
    return {"ok": True}


@router.get("/sources")
async def list_sources():
    sources = db.get_sources()
    profiles = {p.source_id: p for p in db.get_source_profiles() if p.source_id is not None}
    return {"sources": [source_to_dict(s, profiles.get(s.id)) for s in sources]}


@router.post("/sources/{source_id}/trigger")
async def trigger_source(source_id: int):
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await run_fetch(source)
    return {"ok": True}


@router.get("/source-profiles")
async def list_source_profiles():
    return {"profiles": [profile_to_dict(p) for p in db.get_source_profiles()]}


@router.get("/deepseek/settings")
async def get_deepseek_settings():
    return {"settings": deepseek_settings_to_dict(db.get_deepseek_settings())}


@router.post("/deepseek/settings")
async def save_deepseek_settings(payload: DeepSeekSettingsRequest):
    settings = db.update_deepseek_settings(
        api_key=payload.api_key,
        base_url=payload.base_url,
        analysis_model=payload.analysis_model,
        draft_model=payload.draft_model,
        enabled=payload.enabled,
        clear_api_key=payload.clear_api_key,
    )
    return {"ok": True, "settings": deepseek_settings_to_dict(settings)}


@router.post("/deepseek/test")
async def test_deepseek():
    settings = db.get_deepseek_settings()
    if not settings.api_key:
        raise HTTPException(status_code=400, detail="请先保存 DeepSeek API key")
    try:
        response = DeepSeekClient(settings, timeout=25).chat(
            model=settings.analysis_model,
            messages=[
                {"role": "system", "content": "你是连接测试助手。"},
                {"role": "user", "content": "请只回复：DeepSeek 连接正常"},
            ],
            thinking="disabled",
            max_tokens=40,
            temperature=0,
        )
    except DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "model": response.model, "response": response.content[:120]}


@router.get("/candidates")
async def list_candidates(
    limit: int = Query(100, ge=1, le=300),
    status: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
):
    candidates = db.get_candidates(limit=limit, status=status, category=category, q=q)
    return {"candidates": [candidate_to_dict(c) for c in candidates]}


@router.post("/candidates/import")
async def import_candidate(payload: ImportCandidateRequest):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    candidate_id = workflow.ingest_candidate(
        title=payload.title,
        url=payload.url,
        summary=payload.summary,
        content=payload.content,
        source_name=payload.source_name or "手动导入",
        source_type="manual",
        published_at=payload.published_at,
        media_urls=payload.media_urls,
    )
    candidate = db.get_candidate(candidate_id)
    return {"ok": True, "candidate": candidate_to_dict(candidate) if candidate else None}


@router.post("/candidates/{candidate_id}/analyze")
async def analyze_candidate(candidate_id: int):
    try:
        cluster_id = workflow.process_candidate(candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    cluster = db.get_cluster(cluster_id)
    return {"ok": True, "cluster": cluster_to_dict(cluster) if cluster else None}


@router.post("/candidates/{candidate_id}/reanalyze")
async def reanalyze_candidate(candidate_id: int):
    try:
        cluster_id = workflow.reanalyze_candidate(candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    cluster = db.get_cluster(cluster_id)
    candidate = db.get_candidate(candidate_id)
    return {
        "ok": True,
        "candidate": candidate_to_dict(candidate) if candidate else None,
        "cluster": cluster_to_dict(cluster) if cluster else None,
    }


@router.post("/analysis-runs")
async def run_analysis_batch(payload: AnalysisRunRequest):
    if payload.scope not in {"all", "unreviewed", "high-score"}:
        raise HTTPException(status_code=400, detail="Invalid analysis scope")
    result = workflow.run_analysis_batch(scope=payload.scope, limit=payload.limit)
    return {"ok": True, "result": result}


@router.post("/summaries/backfill")
async def backfill_summaries(payload: SummaryBackfillRequest):
    result = workflow.backfill_chinese_summaries(limit=payload.limit)
    return {"ok": True, "result": result}


@router.get("/clusters")
async def list_clusters(
    status: Optional[str] = None,
    category: Optional[str] = None,
    selected_only: bool = False,
    limit: int = Query(120, ge=1, le=300),
):
    clusters = db.get_clusters(status=status, category=category, limit=limit, selected_only=selected_only)
    return {"clusters": [cluster_to_dict(c) for c in clusters]}


@router.post("/clusters/rebuild")
async def rebuild_clusters(payload: RebuildClustersRequest):
    result = workflow.rebuild_unreviewed_clusters(limit=payload.limit, reanalyze=payload.reanalyze)
    return {"ok": True, "result": result}


@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: int):
    cluster = db.get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"cluster": cluster_to_dict(cluster), "candidates": [candidate_to_dict(c) for c in db.get_cluster_candidates(cluster_id)]}


@router.post("/clusters/{cluster_id}/status")
async def update_cluster_status(cluster_id: int, payload: ClusterUpdateRequest):
    cluster = db.get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    updates = payload.dict(exclude_unset=True)
    try:
        db.update_cluster(cluster_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    updated = db.get_cluster(cluster_id)
    return {"ok": True, "cluster": cluster_to_dict(updated) if updated else None}


@router.get("/issues")
async def list_issues(limit: int = Query(20, ge=1, le=100)):
    return {"issues": [issue_to_dict(i) for i in db.get_issues(limit=limit)]}


@router.get("/issues/{issue_id}")
async def get_issue(issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {
        "issue": issue_to_dict(issue),
        "clusters": [cluster_to_dict(c) for c in db.get_issue_clusters(issue_id)],
    }


@router.post("/issues/today/generate")
async def generate_today_issue(payload: Optional[GenerateIssueRequest] = None):
    payload = payload or GenerateIssueRequest()
    issue_date = payload.issue_date or date.today().isoformat()
    cluster_ids = payload.cluster_ids
    if cluster_ids is None:
        cluster_ids = [c.id for c in db.get_clusters(selected_only=True, limit=80)]
    issue = db.create_or_update_issue(issue_date, cluster_ids)
    exports = daily_renderer.export_issue(issue.id)
    issue = db.get_issue(issue.id)
    return {"ok": True, "issue": issue_to_dict(issue), "exports": exports}


@router.post("/issues/{issue_id}/export")
async def export_issue(issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    exports = daily_renderer.export_issue(issue_id)
    issue = db.get_issue(issue_id)
    return {"ok": True, "issue": issue_to_dict(issue), "exports": exports}


@router.get("/daily/stats")
async def daily_stats():
    candidates = db.get_candidates(limit=300)
    clusters = db.get_clusters(limit=300)
    issues = db.get_issues(limit=20)
    return {
        "candidates": len(candidates),
        "clusters": len(clusters),
        "selected": len([c for c in clusters if c.status in {"selected", "drafted"}]),
        "issues": len(issues),
        "categories": db.CATEGORIES,
    }
