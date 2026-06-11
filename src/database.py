import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT_DIR = Path(sys._MEIPASS)
else:
    ROOT_DIR = Path(__file__).parent.parent

DB_PATH = ROOT_DIR / "infohub.db"
EXPORT_ROOT = ROOT_DIR / "exports" / "daily"

CATEGORIES = ["要闻", "模型发布", "开发生态", "产品应用", "技术与洞察", "行业动态", "前瞻与传闻"]
CLUSTER_STATUSES = {"pending", "ignored", "candidate", "selected", "drafted"}
PROTECTED_CLUSTER_STATUSES = {"selected", "ignored", "drafted"}
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_ANALYSIS_MODEL = "deepseek-v4-flash"
DEFAULT_DRAFT_MODEL = "deepseek-v4-pro"


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS feed_source (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('rss', 'github', 'hackernews', 'arxiv')),
            config TEXT NOT NULL DEFAULT '{}',
            description TEXT,
            interval_minutes INTEGER NOT NULL DEFAULT 30,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS feed_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            source_name TEXT NOT NULL,
            published_at TEXT,
            fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER NOT NULL DEFAULT 0,
            ai_summary TEXT,
            is_starred INTEGER NOT NULL DEFAULT 0,
            UNIQUE(url)
        );

        CREATE TABLE IF NOT EXISTS source_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            credibility INTEGER NOT NULL DEFAULT 60,
            default_category TEXT NOT NULL DEFAULT '技术与洞察',
            use_for_daily INTEGER NOT NULL DEFAULT 1,
            collection_method TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, source_type)
        );

        CREATE TABLE IF NOT EXISTS candidate_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            normalized_title TEXT,
            summary TEXT,
            content TEXT,
            url TEXT,
            canonical_url TEXT,
            source_id INTEGER,
            source_profile_id INTEGER,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            published_at TEXT,
            collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            media_urls TEXT NOT NULL DEFAULT '[]',
            content_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'new',
            cluster_id INTEGER,
            ai_summary TEXT,
            keywords TEXT NOT NULL DEFAULT '[]',
            category TEXT NOT NULL DEFAULT '技术与洞察',
            score INTEGER NOT NULL DEFAULT 0,
            score_reason TEXT,
            risk_flags TEXT NOT NULL DEFAULT '[]',
            dedupe_note TEXT,
            analysis_provider TEXT NOT NULL DEFAULT 'rule',
            analysis_version TEXT NOT NULL DEFAULT 'rule-v2',
            analysis_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS event_cluster (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            selected_title TEXT,
            category TEXT NOT NULL DEFAULT '技术与洞察',
            keywords TEXT NOT NULL DEFAULT '[]',
            summary TEXT,
            score INTEGER NOT NULL DEFAULT 0,
            score_reason TEXT,
            score_breakdown TEXT NOT NULL DEFAULT '{}',
            confidence INTEGER NOT NULL DEFAULT 50,
            risk_flags TEXT NOT NULL DEFAULT '[]',
            merge_reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            primary_url TEXT,
            sources TEXT NOT NULL DEFAULT '[]',
            editor_note TEXT,
            draft_body TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_issue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_date TEXT NOT NULL UNIQUE,
            issue_no INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            markdown_path TEXT,
            html_path TEXT,
            assets_path TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_issue_item (
            issue_id INTEGER NOT NULL,
            cluster_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL,
            category TEXT NOT NULL,
            PRIMARY KEY(issue_id, cluster_id)
        );

        CREATE TABLE IF NOT EXISTS deepseek_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            api_key TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT 'https://api.deepseek.com',
            analysis_model TEXT NOT NULL DEFAULT 'deepseek-v4-flash',
            draft_model TEXT NOT NULL DEFAULT 'deepseek-v4-pro',
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_item_fetched ON feed_item(fetched_at DESC);
        CREATE INDEX IF NOT EXISTS idx_item_read ON feed_item(is_read);
        CREATE INDEX IF NOT EXISTS idx_item_starred ON feed_item(is_starred);
        CREATE INDEX IF NOT EXISTS idx_candidate_collected ON candidate_item(collected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate_item(status);
        CREATE INDEX IF NOT EXISTS idx_candidate_cluster ON candidate_item(cluster_id);
        CREATE INDEX IF NOT EXISTS idx_cluster_status ON event_cluster(status);
        CREATE INDEX IF NOT EXISTS idx_cluster_category ON event_cluster(category);
        CREATE INDEX IF NOT EXISTS idx_issue_date ON daily_issue(issue_date DESC);
    """)
    _migrate_schema(conn)
    conn.commit()
    _ensure_source_profiles(conn)
    _ensure_deepseek_settings(conn)
    conn.close()


@dataclass
class FeedSource:
    id: int
    name: str
    type: str
    config: dict
    description: str
    interval_minutes: int
    enabled: bool
    created_at: str


@dataclass
class FeedItem:
    id: int
    title: str
    summary: Optional[str]
    url: str
    source_id: int
    source_name: str
    published_at: Optional[str]
    fetched_at: str
    ai_summary: Optional[str]
    is_read: bool
    is_starred: bool


@dataclass
class SourceProfile:
    id: int
    source_id: Optional[int]
    name: str
    source_type: str
    credibility: int
    default_category: str
    use_for_daily: bool
    collection_method: str


@dataclass
class DeepSeekSettings:
    api_key: str
    base_url: str
    analysis_model: str
    draft_model: str
    enabled: bool
    updated_at: str


@dataclass
class CandidateItem:
    id: int
    title: str
    normalized_title: str
    summary: str
    content: str
    url: str
    canonical_url: str
    source_id: Optional[int]
    source_profile_id: Optional[int]
    source_name: str
    source_type: str
    published_at: Optional[str]
    collected_at: str
    media_urls: List[str]
    content_hash: str
    status: str
    cluster_id: Optional[int]
    ai_summary: str
    keywords: List[str]
    category: str
    score: int
    score_reason: str
    risk_flags: List[str]
    dedupe_note: str
    analysis_provider: str
    analysis_version: str
    analysis_error: str


@dataclass
class EventCluster:
    id: int
    event_key: str
    title: str
    selected_title: str
    category: str
    keywords: List[str]
    summary: str
    score: int
    score_reason: str
    score_breakdown: Dict
    confidence: int
    risk_flags: List[str]
    merge_reason: str
    status: str
    primary_url: str
    sources: List[dict]
    editor_note: str
    draft_body: str
    created_at: str
    updated_at: str


@dataclass
class DailyIssue:
    id: int
    issue_date: str
    issue_no: int
    title: str
    status: str
    markdown_path: str
    html_path: str
    assets_path: str
    created_at: str
    updated_at: str


def _json_list(value: Optional[str]) -> List:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _json_dict(value: Optional[str]) -> Dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    _add_columns(
        conn,
        "candidate_item",
        {
            "normalized_title": "TEXT",
            "canonical_url": "TEXT",
            "analysis_provider": "TEXT NOT NULL DEFAULT 'rule'",
            "analysis_version": "TEXT NOT NULL DEFAULT 'rule-v2'",
            "analysis_error": "TEXT",
        },
    )
    _add_columns(
        conn,
        "event_cluster",
        {
            "score_breakdown": "TEXT NOT NULL DEFAULT '{}'",
            "confidence": "INTEGER NOT NULL DEFAULT 50",
            "merge_reason": "TEXT",
        },
    )
    conn.execute(
        """
        UPDATE candidate_item
        SET normalized_title = COALESCE(NULLIF(normalized_title, ''), ?),
            canonical_url = COALESCE(NULLIF(canonical_url, ''), url)
        WHERE normalized_title IS NULL OR normalized_title = '' OR canonical_url IS NULL
        """,
        ("",),
    )
    rows = conn.execute("SELECT id, title, url FROM candidate_item").fetchall()
    for row in rows:
        conn.execute(
            "UPDATE candidate_item SET normalized_title = ?, canonical_url = ? WHERE id = ?",
            (normalize_news_title(row["title"]), canonicalize_url(row["url"] or ""), row["id"]),
        )


def _add_columns(conn: sqlite3.Connection, table: str, columns: Dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _ensure_deepseek_settings(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO deepseek_settings
        (id, api_key, base_url, analysis_model, draft_model, enabled, updated_at)
        VALUES (1, '', ?, ?, ?, 0, ?)
        """,
        (DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_ANALYSIS_MODEL, DEFAULT_DRAFT_MODEL, utc_now()),
    )


def normalize_category(category: Optional[str]) -> str:
    return category if category in CATEGORIES else "技术与洞察"


def normalize_news_title(title: str) -> str:
    value = re.sub(r"\s+", " ", title or "").strip()
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


def _source_defaults(source_type: str) -> Dict[str, object]:
    if source_type == "github":
        return {"credibility": 65, "default_category": "开发生态"}
    if source_type == "arxiv":
        return {"credibility": 75, "default_category": "技术与洞察"}
    if source_type == "hackernews":
        return {"credibility": 55, "default_category": "前瞻与传闻"}
    if source_type == "manual":
        return {"credibility": 70, "default_category": "要闻"}
    return {"credibility": 60, "default_category": "技术与洞察"}


def _ensure_source_profiles(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, name, type FROM feed_source").fetchall()
    for row in rows:
        defaults = _source_defaults(row["type"])
        conn.execute(
            """
            INSERT OR IGNORE INTO source_profile
            (source_id, name, source_type, credibility, default_category, collection_method)
            VALUES (?, ?, ?, ?, ?, 'auto')
            """,
            (row["id"], row["name"], row["type"], defaults["credibility"], defaults["default_category"]),
        )
    defaults = _source_defaults("manual")
    conn.execute(
        """
        INSERT OR IGNORE INTO source_profile
        (source_id, name, source_type, credibility, default_category, collection_method)
        VALUES (NULL, '手动导入', 'manual', ?, ?, 'paste')
        """,
        (defaults["credibility"], defaults["default_category"]),
    )
    conn.commit()


# ---------- FeedSource CRUD ----------

def create_source(name: str, type: str, config: dict, description: str = "", interval_minutes: int = 30, enabled: bool = True) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO feed_source (name, type, config, description, interval_minutes, enabled) VALUES (?, ?, ?, ?, ?, ?)",
        (name, type, _dump(config), description, interval_minutes, int(enabled)),
    )
    conn.commit()
    _ensure_source_profiles(conn)
    conn.close()
    return cur.lastrowid  # type: ignore[return-value]


def get_sources(enabled_only: bool = False) -> List[FeedSource]:
    conn = get_conn()
    sql = "SELECT * FROM feed_source"
    if enabled_only:
        sql += " WHERE enabled = 1"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [_row_to_source(r) for r in rows]


def get_source(source_id: int) -> Optional[FeedSource]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM feed_source WHERE id = ?", (source_id,)).fetchone()
    conn.close()
    return _row_to_source(row) if row else None


def update_source(source_id: int, **kwargs) -> None:
    allowed = {"name", "type", "config", "description", "interval_minutes", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    if "config" in updates:
        updates["config"] = _dump(updates["config"])
    if "enabled" in updates:
        updates["enabled"] = int(updates["enabled"])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [source_id]
    conn = get_conn()
    conn.execute(f"UPDATE feed_source SET {set_clause} WHERE id = ?", values)
    conn.commit()
    _ensure_source_profiles(conn)
    conn.close()


def delete_source(source_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM feed_source WHERE id = ?", (source_id,))
    conn.execute("UPDATE source_profile SET use_for_daily = 0 WHERE source_id = ?", (source_id,))
    conn.commit()
    conn.close()


def _row_to_source(row: sqlite3.Row) -> FeedSource:
    return FeedSource(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        config=_json_dict(row["config"]),
        description=row["description"] or "",
        interval_minutes=row["interval_minutes"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
    )


# ---------- FeedItem CRUD ----------

def insert_items(items: List[dict]) -> List[int]:
    conn = get_conn()
    inserted_ids = []
    now = utc_now()
    for it in items:
        try:
            cur = conn.execute(
                """
                INSERT INTO feed_item (title, summary, url, source_id, source_name, published_at, fetched_at, ai_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it["title"],
                    it.get("summary", ""),
                    it["url"],
                    it["source_id"],
                    it["source_name"],
                    it.get("published_at"),
                    now,
                    it.get("ai_summary", ""),
                ),
            )
            inserted_ids.append(cur.lastrowid)
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return inserted_ids  # type: ignore[return-value]


def get_items(limit: int = 100, offset: int = 0, source_id: Optional[int] = None, is_read: Optional[bool] = None, is_starred: Optional[bool] = None) -> List[FeedItem]:
    conn = get_conn()
    conditions = []
    params: list = []
    if source_id is not None:
        conditions.append("source_id = ?")
        params.append(source_id)
    if is_read is not None:
        conditions.append("is_read = ?")
        params.append(int(is_read))
    if is_starred is not None:
        conditions.append("is_starred = ?")
        params.append(int(is_starred))
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM feed_item {where} ORDER BY fetched_at DESC LIMIT ? OFFSET ?"
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    conn.close()
    return [_row_to_item(r) for r in rows]


def get_item(item_id: int) -> Optional[FeedItem]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM feed_item WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return _row_to_item(row) if row else None


def mark_read(item_id: int, is_read: bool = True) -> None:
    conn = get_conn()
    conn.execute("UPDATE feed_item SET is_read = ? WHERE id = ?", (int(is_read), item_id))
    conn.commit()
    conn.close()


def mark_starred(item_id: int, is_starred: bool = True) -> None:
    conn = get_conn()
    conn.execute("UPDATE feed_item SET is_starred = ? WHERE id = ?", (int(is_starred), item_id))
    conn.commit()
    conn.close()


def search_items(query: str, limit: int = 50) -> List[FeedItem]:
    conn = get_conn()
    pattern = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM feed_item WHERE title LIKE ? OR summary LIKE ? ORDER BY fetched_at DESC LIMIT ?",
        (pattern, pattern, limit),
    ).fetchall()
    conn.close()
    return [_row_to_item(r) for r in rows]


def _row_to_item(row: sqlite3.Row) -> FeedItem:
    return FeedItem(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        url=row["url"],
        source_id=row["source_id"],
        source_name=row["source_name"],
        published_at=row["published_at"],
        fetched_at=row["fetched_at"],
        ai_summary=row["ai_summary"],
        is_read=bool(row["is_read"]),
        is_starred=bool(row["is_starred"]),
    )


# ---------- Daily production source profiles ----------

def get_source_profile(source_id: Optional[int] = None, source_name: str = "手动导入", source_type: str = "manual") -> SourceProfile:
    conn = get_conn()
    _ensure_source_profiles(conn)
    if source_id is not None:
        row = conn.execute("SELECT * FROM source_profile WHERE source_id = ?", (source_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM source_profile WHERE name = ? AND source_type = ?",
            (source_name, source_type),
        ).fetchone()
    if not row:
        defaults = _source_defaults(source_type)
        cur = conn.execute(
            """
            INSERT INTO source_profile
            (source_id, name, source_type, credibility, default_category, collection_method)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source_name,
                source_type,
                defaults["credibility"],
                defaults["default_category"],
                "paste" if source_type == "manual" else "auto",
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM source_profile WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return _row_to_profile(row)


def get_source_profiles() -> List[SourceProfile]:
    conn = get_conn()
    _ensure_source_profiles(conn)
    rows = conn.execute("SELECT * FROM source_profile ORDER BY collection_method, name").fetchall()
    conn.close()
    return [_row_to_profile(r) for r in rows]


def _row_to_profile(row: sqlite3.Row) -> SourceProfile:
    return SourceProfile(
        id=row["id"],
        source_id=row["source_id"],
        name=row["name"],
        source_type=row["source_type"],
        credibility=row["credibility"],
        default_category=row["default_category"],
        use_for_daily=bool(row["use_for_daily"]),
        collection_method=row["collection_method"],
    )


# ---------- DeepSeek settings ----------

def get_deepseek_settings() -> DeepSeekSettings:
    conn = get_conn()
    _ensure_deepseek_settings(conn)
    row = conn.execute("SELECT * FROM deepseek_settings WHERE id = 1").fetchone()
    conn.close()
    return _row_to_deepseek_settings(row)


def update_deepseek_settings(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    analysis_model: Optional[str] = None,
    draft_model: Optional[str] = None,
    enabled: Optional[bool] = None,
    clear_api_key: bool = False,
) -> DeepSeekSettings:
    updates = {}
    if clear_api_key:
        updates["api_key"] = ""
    elif api_key is not None:
        updates["api_key"] = api_key.strip()
    if base_url is not None:
        updates["base_url"] = base_url.strip().rstrip("/") or DEFAULT_DEEPSEEK_BASE_URL
    if analysis_model is not None:
        updates["analysis_model"] = analysis_model.strip() or DEFAULT_ANALYSIS_MODEL
    if draft_model is not None:
        updates["draft_model"] = draft_model.strip() or DEFAULT_DRAFT_MODEL
    if enabled is not None:
        updates["enabled"] = int(enabled)
    updates["updated_at"] = utc_now()

    conn = get_conn()
    _ensure_deepseek_settings(conn)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE deepseek_settings SET {set_clause} WHERE id = 1", values)
    conn.commit()
    row = conn.execute("SELECT * FROM deepseek_settings WHERE id = 1").fetchone()
    conn.close()
    return _row_to_deepseek_settings(row)


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def _row_to_deepseek_settings(row: sqlite3.Row) -> DeepSeekSettings:
    return DeepSeekSettings(
        api_key=row["api_key"] or "",
        base_url=row["base_url"] or DEFAULT_DEEPSEEK_BASE_URL,
        analysis_model=row["analysis_model"] or DEFAULT_ANALYSIS_MODEL,
        draft_model=row["draft_model"] or DEFAULT_DRAFT_MODEL,
        enabled=bool(row["enabled"]),
        updated_at=row["updated_at"],
    )


# ---------- Candidate and cluster workflow ----------

def upsert_candidate(
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
    profile = get_source_profile(source_id=source_id, source_name=source_name, source_type=source_type)
    media_urls = media_urls or []
    normalized_title = normalize_news_title(title)
    canonical_url = canonicalize_url(url)
    content_hash = compute_content_hash(title, canonical_url, summary, content)
    conn = get_conn()
    now = utc_now()
    try:
        cur = conn.execute(
            """
            INSERT INTO candidate_item
            (title, normalized_title, summary, content, url, canonical_url, source_id, source_profile_id,
             source_name, source_type, published_at, collected_at, media_urls, content_hash, category,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip() or "未命名资讯",
                normalized_title,
                summary.strip(),
                content.strip(),
                url.strip(),
                canonical_url,
                source_id,
                profile.id,
                source_name,
                source_type,
                published_at,
                now,
                _dump(media_urls),
                content_hash,
                profile.default_category,
                now,
                now,
            ),
        )
        candidate_id = cur.lastrowid
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM candidate_item WHERE content_hash = ?", (content_hash,)).fetchone()
        candidate_id = row["id"]
        conn.execute(
            """
            UPDATE candidate_item
            SET summary = COALESCE(NULLIF(summary, ''), ?),
                content = COALESCE(NULLIF(content, ''), ?),
                media_urls = CASE WHEN media_urls = '[]' THEN ? ELSE media_urls END,
                updated_at = ?
            WHERE id = ?
            """,
            (summary.strip(), content.strip(), _dump(media_urls), now, candidate_id),
        )
    conn.commit()
    conn.close()
    return int(candidate_id)


def get_candidate(candidate_id: int) -> Optional[CandidateItem]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM candidate_item WHERE id = ?", (candidate_id,)).fetchone()
    conn.close()
    return _row_to_candidate(row) if row else None


def get_candidates(limit: int = 100, status: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None) -> List[CandidateItem]:
    conn = get_conn()
    conditions = []
    params: list = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if q:
        conditions.append("(title LIKE ? OR summary LIKE ? OR content LIKE ?)")
        pattern = f"%{q}%"
        params.extend([pattern, pattern, pattern])
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM candidate_item {where} ORDER BY collected_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [_row_to_candidate(r) for r in rows]


def get_candidate_ids_for_analysis(scope: str = "unreviewed", limit: int = 50) -> List[int]:
    scope = (scope or "unreviewed").lower()
    conn = get_conn()
    params: list = []
    where = ""
    if scope == "unreviewed":
        where = """
        WHERE c.cluster_id IS NULL
           OR ec.id IS NULL
           OR ec.status NOT IN ('selected', 'ignored', 'drafted')
        """
    elif scope == "high-score":
        where = """
        WHERE c.score >= 65
          AND (ec.id IS NULL OR ec.status NOT IN ('selected', 'ignored', 'drafted'))
        """
    elif scope != "all":
        conn.close()
        return []
    rows = conn.execute(
        f"""
        SELECT c.id
        FROM candidate_item c
        LEFT JOIN event_cluster ec ON ec.id = c.cluster_id
        {where}
        ORDER BY c.collected_at DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    conn.close()
    return [int(row["id"]) for row in rows]


def detach_unreviewed_clusters(limit: int = 500) -> List[int]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.id, c.cluster_id
        FROM candidate_item c
        LEFT JOIN event_cluster ec ON ec.id = c.cluster_id
        WHERE c.cluster_id IS NULL
           OR ec.id IS NULL
           OR ec.status NOT IN ('selected', 'ignored', 'drafted')
        ORDER BY c.collected_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    candidate_ids = {int(row["id"]) for row in rows}
    cluster_ids = {int(row["cluster_id"]) for row in rows if row["cluster_id"] is not None}
    if cluster_ids:
        placeholders = ",".join("?" for _ in cluster_ids)
        linked_rows = conn.execute(
            f"SELECT id FROM candidate_item WHERE cluster_id IN ({placeholders})",
            list(cluster_ids),
        ).fetchall()
        candidate_ids.update(int(row["id"]) for row in linked_rows)
    if candidate_ids:
        placeholders = ",".join("?" for _ in candidate_ids)
        conn.execute(
            f"""
            UPDATE candidate_item
            SET cluster_id = NULL, status = 'new', dedupe_note = NULL, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [utc_now()] + list(candidate_ids),
        )
    if cluster_ids:
        placeholders = ",".join("?" for _ in cluster_ids)
        conn.execute(
            f"DELETE FROM event_cluster WHERE id IN ({placeholders}) AND status NOT IN ('selected', 'ignored', 'drafted')",
            list(cluster_ids),
        )
    conn.commit()
    conn.close()
    return list(candidate_ids)


def merge_candidate_analysis(candidate_id: int, analysis: dict) -> int:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Candidate not found")

    category = normalize_category(analysis.get("category"))
    keywords = analysis.get("keywords") or []
    risk_flags = analysis.get("risk_flags") or []
    score = max(0, min(100, int(analysis.get("score") or 0)))
    score_breakdown = analysis.get("score_breakdown") or {}
    confidence = max(0, min(100, int(analysis.get("confidence") or 50)))
    merge_reason = analysis.get("merge_reason") or ""
    normalized_title = normalize_news_title(analysis.get("event_title") or candidate.normalized_title or candidate.title)
    canonical_url = analysis.get("canonical_url") or candidate.canonical_url or canonicalize_url(candidate.url)
    event_key = analysis.get("event_key") or make_event_key(category, normalized_title, keywords, canonical_url)
    title = analysis.get("event_title") or normalized_title or candidate.title
    recommended_status = normalize_recommended_status(analysis.get("recommended_status"), score, risk_flags)
    now = utc_now()

    conn = get_conn()
    cluster_row = conn.execute("SELECT * FROM event_cluster WHERE event_key = ?", (event_key,)).fetchone()
    if not cluster_row:
        cluster_row = _find_similar_cluster(conn, title, category, keywords, canonical_url)

    source_ref = {
        "candidate_id": candidate.id,
        "source_name": candidate.source_name,
        "source_type": candidate.source_type,
        "url": candidate.url,
        "canonical_url": canonical_url,
        "title": candidate.title,
        "analysis_provider": analysis.get("analysis_provider", "rule"),
    }

    if cluster_row:
        cluster_id = cluster_row["id"]
        sources = _json_list(cluster_row["sources"])
        if not any(s.get("candidate_id") == candidate.id for s in sources):
            sources.append(source_ref)
        merged_keywords = _merge_lists(_json_list(cluster_row["keywords"]), keywords)
        merged_risks = _merge_lists(_json_list(cluster_row["risk_flags"]), risk_flags)
        merged_breakdown = _merge_score_breakdown(_json_dict(cluster_row["score_breakdown"]), score_breakdown)
        next_score = max(cluster_row["score"], score)
        next_confidence = max(cluster_row["confidence"], confidence)
        conn.execute(
            """
            UPDATE event_cluster
            SET keywords = ?, summary = COALESCE(NULLIF(summary, ''), ?), score = ?, score_reason = ?,
                score_breakdown = ?, confidence = ?, risk_flags = ?, merge_reason = ?,
                sources = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                _dump(merged_keywords),
                analysis.get("summary", ""),
                next_score,
                analysis.get("score_reason", ""),
                _dump(merged_breakdown),
                next_confidence,
                _dump(merged_risks),
                merge_reason or cluster_row["merge_reason"] or "标题、关键词或规范化链接相近",
                _dump(sources),
                now,
                cluster_id,
            ),
        )
        dedupe_note = merge_reason or "已归并到相似事件"
    else:
        initial_status = recommended_status
        cur = conn.execute(
            """
            INSERT INTO event_cluster
            (event_key, title, selected_title, category, keywords, summary, score, score_reason,
             score_breakdown, confidence, risk_flags, merge_reason, status, primary_url, sources,
             draft_body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_key,
                title,
                title,
                category,
                _dump(keywords),
                analysis.get("summary", ""),
                score,
                analysis.get("score_reason", ""),
                _dump(score_breakdown),
                confidence,
                _dump(risk_flags),
                merge_reason,
                initial_status,
                candidate.url,
                _dump([source_ref]),
                analysis.get("draft_body", ""),
                now,
                now,
            ),
        )
        cluster_id = cur.lastrowid
        dedupe_note = "新事件"

    conn.execute(
        """
        UPDATE candidate_item
        SET status = 'clustered', cluster_id = ?, normalized_title = ?, canonical_url = ?,
            ai_summary = ?, keywords = ?, category = ?, score = ?, score_reason = ?,
            risk_flags = ?, dedupe_note = ?, analysis_provider = ?, analysis_version = ?,
            analysis_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            cluster_id,
            normalized_title,
            canonical_url,
            analysis.get("summary", ""),
            _dump(keywords),
            category,
            score,
            analysis.get("score_reason", ""),
            _dump(risk_flags),
            dedupe_note,
            analysis.get("analysis_provider", "rule"),
            analysis.get("analysis_version", "rule-v2"),
            analysis.get("analysis_error", ""),
            now,
            candidate_id,
        ),
    )
    conn.commit()
    conn.close()
    return int(cluster_id)


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


def _find_similar_cluster(
    conn: sqlite3.Connection,
    title: str,
    category: str,
    keywords: Optional[List[str]] = None,
    canonical_url: str = "",
) -> Optional[sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM event_cluster WHERE category = ? ORDER BY updated_at DESC LIMIT 120",
        (category,),
    ).fetchall()
    normalized = normalize_text(title)
    if not normalized:
        return None
    keyword_set = {normalize_text(k) for k in (keywords or []) if normalize_text(k)}
    title_tokens = tokenize_for_similarity(title)
    for row in rows:
        sources = _json_list(row["sources"])
        if canonical_url and any(s.get("canonical_url") == canonical_url for s in sources):
            return row
        ratio = SequenceMatcher(None, normalized, normalize_text(row["title"])).ratio()
        cluster_keywords = {normalize_text(k) for k in _json_list(row["keywords"]) if normalize_text(k)}
        overlap = keyword_set & cluster_keywords
        row_tokens = tokenize_for_similarity(row["title"])
        token_overlap = title_tokens & row_tokens
        token_union = title_tokens | row_tokens
        token_ratio = len(token_overlap) / max(1, len(token_union))
        if ratio >= 0.82 or (ratio >= 0.60 and len(overlap) >= 2) or (token_ratio >= 0.55 and len(token_overlap) >= 4):
            return row
    return None


def tokenize_for_similarity(text: str) -> set:
    tokens = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9._+-]{1,}|[\u4e00-\u9fff]{2,}", text or ""):
        normalized = normalize_text(token)
        if normalized and normalized not in {"发布", "推出", "上线", "测试", "验证"}:
            tokens.add(normalized)
    return tokens


def _merge_lists(a: List, b: List) -> List:
    result = []
    for item in a + b:
        if item and item not in result:
            result.append(item)
    return result[:12]


def _merge_score_breakdown(a: Dict, b: Dict) -> Dict:
    result = dict(a or {})
    for key, value in (b or {}).items():
        if isinstance(value, (int, float)):
            result[key] = max(value, result.get(key, value) or 0)
        elif value and key not in result:
            result[key] = value
    return result


def get_clusters(
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    selected_only: bool = False,
) -> List[EventCluster]:
    conn = get_conn()
    conditions = []
    params: list = []
    if selected_only:
        conditions.append("status IN ('selected', 'drafted')")
    elif status:
        conditions.append("status = ?")
        params.append(status)
    if category:
        conditions.append("category = ?")
        params.append(category)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM event_cluster {where} ORDER BY score DESC, updated_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [_row_to_cluster(r) for r in rows]


def get_cluster(cluster_id: int) -> Optional[EventCluster]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM event_cluster WHERE id = ?", (cluster_id,)).fetchone()
    conn.close()
    return _row_to_cluster(row) if row else None


def get_cluster_candidates(cluster_id: int) -> List[CandidateItem]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM candidate_item WHERE cluster_id = ? ORDER BY score DESC, collected_at DESC",
        (cluster_id,),
    ).fetchall()
    conn.close()
    return [_row_to_candidate(r) for r in rows]


def update_cluster(cluster_id: int, **kwargs) -> None:
    allowed = {"status", "selected_title", "category", "editor_note", "draft_body", "summary"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if "status" in updates and updates["status"] not in CLUSTER_STATUSES:
        raise ValueError("Invalid cluster status")
    if "category" in updates:
        updates["category"] = normalize_category(updates["category"])
    if not updates:
        return
    updates["updated_at"] = utc_now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [cluster_id]
    conn = get_conn()
    conn.execute(f"UPDATE event_cluster SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def _row_to_candidate(row: sqlite3.Row) -> CandidateItem:
    return CandidateItem(
        id=row["id"],
        title=row["title"],
        normalized_title=row["normalized_title"] or normalize_news_title(row["title"]),
        summary=row["summary"] or "",
        content=row["content"] or "",
        url=row["url"] or "",
        canonical_url=row["canonical_url"] or canonicalize_url(row["url"] or ""),
        source_id=row["source_id"],
        source_profile_id=row["source_profile_id"],
        source_name=row["source_name"],
        source_type=row["source_type"],
        published_at=row["published_at"],
        collected_at=row["collected_at"],
        media_urls=_json_list(row["media_urls"]),
        content_hash=row["content_hash"],
        status=row["status"],
        cluster_id=row["cluster_id"],
        ai_summary=row["ai_summary"] or "",
        keywords=_json_list(row["keywords"]),
        category=row["category"],
        score=row["score"],
        score_reason=row["score_reason"] or "",
        risk_flags=_json_list(row["risk_flags"]),
        dedupe_note=row["dedupe_note"] or "",
        analysis_provider=row["analysis_provider"] or "rule",
        analysis_version=row["analysis_version"] or "rule-v2",
        analysis_error=row["analysis_error"] or "",
    )


def _row_to_cluster(row: sqlite3.Row) -> EventCluster:
    return EventCluster(
        id=row["id"],
        event_key=row["event_key"],
        title=row["title"],
        selected_title=row["selected_title"] or row["title"],
        category=row["category"],
        keywords=_json_list(row["keywords"]),
        summary=row["summary"] or "",
        score=row["score"],
        score_reason=row["score_reason"] or "",
        score_breakdown=_json_dict(row["score_breakdown"]),
        confidence=int(row["confidence"] or 50),
        risk_flags=_json_list(row["risk_flags"]),
        merge_reason=row["merge_reason"] or "",
        status=row["status"],
        primary_url=row["primary_url"] or "",
        sources=_json_list(row["sources"]),
        editor_note=row["editor_note"] or "",
        draft_body=row["draft_body"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------- Daily issue workflow ----------

def create_or_update_issue(issue_date: str, cluster_ids: Optional[List[int]] = None) -> DailyIssue:
    conn = get_conn()
    row = conn.execute("SELECT * FROM daily_issue WHERE issue_date = ?", (issue_date,)).fetchone()
    if row:
        issue_id = row["id"]
    else:
        max_row = conn.execute("SELECT MAX(issue_no) AS max_no FROM daily_issue").fetchone()
        next_no = int(max_row["max_no"] or 0) + 1
        cur = conn.execute(
            """
            INSERT INTO daily_issue (issue_date, issue_no, title, status, created_at, updated_at)
            VALUES (?, ?, ?, 'draft', ?, ?)
            """,
            (issue_date, next_no, f"AI 日报 {issue_date}", utc_now(), utc_now()),
        )
        issue_id = cur.lastrowid
    if cluster_ids is not None:
        conn.execute("DELETE FROM daily_issue_item WHERE issue_id = ?", (issue_id,))
        for index, cluster_id in enumerate(cluster_ids, start=1):
            cluster = conn.execute("SELECT category FROM event_cluster WHERE id = ?", (cluster_id,)).fetchone()
            if cluster:
                conn.execute(
                    "INSERT OR REPLACE INTO daily_issue_item (issue_id, cluster_id, sort_order, category) VALUES (?, ?, ?, ?)",
                    (issue_id, cluster_id, index, cluster["category"]),
                )
        conn.execute("UPDATE daily_issue SET updated_at = ? WHERE id = ?", (utc_now(), issue_id))
    conn.commit()
    row = conn.execute("SELECT * FROM daily_issue WHERE id = ?", (issue_id,)).fetchone()
    conn.close()
    return _row_to_issue(row)


def get_issue(issue_id: int) -> Optional[DailyIssue]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM daily_issue WHERE id = ?", (issue_id,)).fetchone()
    conn.close()
    return _row_to_issue(row) if row else None


def get_issue_by_date(issue_date: str) -> Optional[DailyIssue]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM daily_issue WHERE issue_date = ?", (issue_date,)).fetchone()
    conn.close()
    return _row_to_issue(row) if row else None


def get_issues(limit: int = 20) -> List[DailyIssue]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM daily_issue ORDER BY issue_date DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [_row_to_issue(r) for r in rows]


def get_issue_clusters(issue_id: int) -> List[EventCluster]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.*
        FROM daily_issue_item i
        JOIN event_cluster c ON c.id = i.cluster_id
        WHERE i.issue_id = ?
        ORDER BY i.sort_order ASC
        """,
        (issue_id,),
    ).fetchall()
    conn.close()
    return [_row_to_cluster(r) for r in rows]


def save_issue_exports(issue_id: int, markdown_path: str, html_path: str, assets_path: str) -> None:
    conn = get_conn()
    conn.execute(
        """
        UPDATE daily_issue
        SET markdown_path = ?, html_path = ?, assets_path = ?, status = 'exported', updated_at = ?
        WHERE id = ?
        """,
        (markdown_path, html_path, assets_path, utc_now(), issue_id),
    )
    conn.commit()
    conn.close()


def _row_to_issue(row: sqlite3.Row) -> DailyIssue:
    return DailyIssue(
        id=row["id"],
        issue_date=row["issue_date"],
        issue_no=row["issue_no"],
        title=row["title"],
        status=row["status"],
        markdown_path=row["markdown_path"] or "",
        html_path=row["html_path"] or "",
        assets_path=row["assets_path"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
