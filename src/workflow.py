from typing import List, Optional

import ai_workflow
import database as db
from fetchers.summarizer import generate_summary, needs_chinese_summary, rule_chinese_summary


def process_candidate(candidate_id: int) -> int:
    candidate = db.get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Candidate not found")
    profile = db.get_source_profile(
        source_id=candidate.source_id,
        source_name=candidate.source_name,
        source_type=candidate.source_type,
    )
    analysis = ai_workflow.get_daily_ai().analyze_candidate(candidate, profile)
    return db.merge_candidate_analysis(candidate_id, analysis)


def reanalyze_candidate(candidate_id: int) -> int:
    return process_candidate(candidate_id)


def run_analysis_batch(scope: str = "unreviewed", limit: int = 50) -> dict:
    candidate_ids = db.get_candidate_ids_for_analysis(scope=scope, limit=limit)
    processed = 0
    errors = []
    for candidate_id in candidate_ids:
        try:
            process_candidate(candidate_id)
            processed += 1
        except Exception as exc:
            errors.append({"candidate_id": candidate_id, "error": str(exc)})
    return {
        "scope": scope,
        "requested": len(candidate_ids),
        "processed": processed,
        "errors": errors,
    }


def rebuild_unreviewed_clusters(limit: int = 500, reanalyze: bool = False) -> dict:
    candidate_ids = db.detach_unreviewed_clusters(limit=limit)
    processed = 0
    errors = []
    for candidate_id in candidate_ids:
        try:
            if reanalyze:
                process_candidate(candidate_id)
            else:
                candidate = db.get_candidate(candidate_id)
                if not candidate:
                    continue
                analysis = analysis_from_candidate(candidate)
                db.merge_candidate_analysis(candidate_id, analysis)
            processed += 1
        except Exception as exc:
            errors.append({"candidate_id": candidate_id, "error": str(exc)})
    return {
        "requested": len(candidate_ids),
        "processed": processed,
        "errors": errors,
    }


def backfill_chinese_summaries(limit: int = 300) -> dict:
    conn = db.get_conn()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT i.id, i.title, i.summary, i.url, i.ai_summary, i.source_id, i.source_name, s.type AS source_type
                FROM feed_item i
                JOIN feed_source s ON s.id = i.source_id
                ORDER BY i.fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
    finally:
        conn.close()
    processed = len(rows)
    updated = 0
    skipped = 0
    failed = []

    for row in rows:
        current = row["ai_summary"] or row["summary"] or row["title"]
        if not needs_chinese_summary(current):
            skipped += 1
            continue
        try:
            new_summary = generate_summary(row["title"], row["summary"] or current, row["source_type"])
            if not new_summary:
                skipped += 1
                continue
            conn = db.get_conn()
            try:
                conn.execute("UPDATE feed_item SET ai_summary = ? WHERE id = ?", (new_summary, row["id"]))
                candidate_ids = _update_matching_candidates(conn, row, new_summary)
                _update_matching_clusters(conn, candidate_ids, new_summary)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            updated += 1
        except Exception as exc:
            failed.append({"item_id": row["id"], "error": str(exc)})

    return {
        "processed": processed,
        "updated": updated,
        "skipped": skipped,
        "failed": len(failed),
        "errors": failed[:10],
    }


def _update_matching_candidates(conn, row, new_summary: str) -> List[int]:
    canonical_url = db.canonicalize_url(row["url"] or "")
    rows = conn.execute(
        """
        SELECT id, cluster_id, summary, ai_summary, content
        FROM candidate_item
        WHERE canonical_url = ? OR url = ? OR content_hash = ?
        """,
        (
            canonical_url,
            row["url"] or "",
            db.compute_content_hash(row["title"], row["url"] or "", row["summary"] or "", row["summary"] or ""),
        ),
    ).fetchall()
    candidate_ids = []
    for candidate in rows:
        candidate_ids.append(candidate["id"])
        summary_value = new_summary if needs_chinese_summary(candidate["summary"] or "") else candidate["summary"]
        conn.execute(
            """
            UPDATE candidate_item
            SET ai_summary = ?, summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_summary, summary_value, db.utc_now(), candidate["id"]),
        )
    return candidate_ids


def _update_matching_clusters(conn, candidate_ids: List[int], new_summary: str) -> None:
    if not candidate_ids:
        return
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT ec.id, ec.summary, ec.draft_body
        FROM candidate_item c
        JOIN event_cluster ec ON ec.id = c.cluster_id
        WHERE c.id IN ({placeholders})
        """,
        candidate_ids,
    ).fetchall()
    for cluster in rows:
        updates = {}
        if needs_chinese_summary(cluster["summary"] or ""):
            updates["summary"] = new_summary
        if needs_chinese_summary(cluster["draft_body"] or ""):
            updates["draft_body"] = new_summary
        if not updates:
            continue
        updates["updated_at"] = db.utc_now()
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE event_cluster SET {set_clause} WHERE id = ?",
            list(updates.values()) + [cluster["id"]],
        )


def analysis_from_candidate(candidate: db.CandidateItem) -> dict:
    keywords = candidate.keywords or []
    category = db.normalize_category(candidate.category)
    event_title = db.normalize_news_title(candidate.normalized_title or candidate.title)
    summary = best_chinese_candidate_summary(candidate)
    return {
        "event_key": db.make_event_key(category, event_title, keywords, candidate.canonical_url),
        "event_title": event_title,
        "canonical_url": candidate.canonical_url,
        "category": category,
        "keywords": keywords,
        "summary": summary,
        "score": candidate.score,
        "score_reason": candidate.score_reason,
        "score_breakdown": infer_score_breakdown(candidate.score, candidate.risk_flags),
        "confidence": 50,
        "risk_flags": candidate.risk_flags,
        "merge_reason": "重聚合：复用现有摘要、关键词和规范化链接",
        "recommended_status": "candidate" if candidate.score >= 55 else "pending",
        "draft_body": summary or candidate.title,
        "analysis_provider": candidate.analysis_provider or "rule",
        "analysis_version": candidate.analysis_version or "rule-v2",
        "analysis_error": candidate.analysis_error,
    }


def best_chinese_candidate_summary(candidate: db.CandidateItem) -> str:
    summary = candidate.ai_summary or candidate.summary or candidate.content or candidate.title
    if needs_chinese_summary(summary):
        return rule_chinese_summary(candidate.title, summary, candidate.source_type)
    return summary


def infer_score_breakdown(score: int, risk_flags: List[str]) -> dict:
    score = max(0, min(100, int(score or 0)))
    rumor_penalty = -8 if any("传闻" in flag for flag in risk_flags) else 0
    remaining = max(0, score - rumor_penalty)
    return {
        "AI相关性": min(20, max(8, int(remaining * 0.22))),
        "来源权威性": min(20, max(6, int(remaining * 0.16))),
        "新鲜度": min(15, max(5, int(remaining * 0.14))),
        "影响力": min(20, max(5, int(remaining * 0.18))),
        "信息完整度": min(15, max(4, int(remaining * 0.14))),
        "重复风险": min(10, max(3, int(remaining * 0.08))),
        "传闻风险": rumor_penalty,
    }


def ingest_candidate(
    title: str,
    url: str = "",
    summary: str = "",
    content: str = "",
    source_id: Optional[int] = None,
    source_name: str = "手动导入",
    source_type: str = "manual",
    published_at: Optional[str] = None,
    media_urls: Optional[List[str]] = None,
) -> int:
    candidate_id = db.upsert_candidate(
        title=title,
        url=url,
        summary=summary,
        content=content,
        source_id=source_id,
        source_name=source_name,
        source_type=source_type,
        published_at=published_at,
        media_urls=media_urls or [],
    )
    process_candidate(candidate_id)
    return candidate_id


def ingest_feed_items(items: List[dict]) -> List[int]:
    candidate_ids = []
    for item in items:
        candidate_id = ingest_candidate(
            title=item["title"],
            url=item.get("url", ""),
            summary=item.get("ai_summary") or item.get("summary", ""),
            content=item.get("summary", ""),
            source_id=item.get("source_id"),
            source_name=item.get("source_name", "未知来源"),
            source_type=item.get("source_type", "rss"),
            published_at=item.get("published_at"),
            media_urls=item.get("media_urls") or [],
        )
        candidate_ids.append(candidate_id)
    return candidate_ids
