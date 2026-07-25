#!/usr/bin/env python3
"""Read-only Question Bank API helpers (Phase 1).

Presents the existing ``qa_content_row`` / ``qa_chapter`` tables as a
searchable, filterable, paginated "item bank" -- WITHOUT any schema change.
One ``qa_content_row`` == one item summary.

``subject`` / ``class`` / ``board`` are *derived* from ``book_slug`` (mirroring
``app_server.guess_attributes_from_name``); they are not columns, so attribute
filters are resolved to the set of matching ``book_slug`` values before hitting
SQL.

Self-contained on purpose: ``viewer_api.py`` is slated for retirement (T19), so
this module owns its own MySQL connection and query helpers instead of importing
from it.  It is imported lazily by ``app_server.py`` so the server still boots
when ``pymysql`` is absent.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pymysql
from pymysql.cursors import DictCursor

from topicwise_pipeline import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

# Optional: connect via a local UNIX socket (e.g. /tmp/mysql.sock) instead of
# TCP host/port.  MySQL treats 'localhost' (socket) as a different host than
# 127.0.0.1 (TCP), so socket auth often differs.
DB_SOCKET = os.environ.get("DB_SOCKET", "").strip()

# ---------------------------------------------------------------------------
# Vocabulary + config (mirrors app_server.py; intentionally kept in sync)
# ---------------------------------------------------------------------------
# NOTE: duplicated rather than imported to avoid a circular import with
# app_server (which imports this module).  If the vocabulary in app_server
# changes, update it here too.
SUBJECTS = ["Physics", "Chemistry", "Biology", "Mathematics", "Science"]

# Whitelisted sort keys -> ORDER BY fragment.  "relevance" has no full-text
# score available on these tables, so it falls back to a stable id ordering.
SORTS = {
    "relevance": "id ASC",
    "newest": "updated_at DESC, id DESC",
    "id": "id ASC",
    "chapter": "chapter_id ASC, id ASC",
    "type": "question_type ASC, id ASC",
    "book": "book_slug ASC, id ASC",
}

PAGE_SIZE_DEFAULT = 25
PAGE_SIZE_MAX = 100

_CLASS_RE = re.compile(r"class\s*(\d{1,2})")
_CLASS_TH_RE = re.compile(r"(\d{1,2})\s*th")
_CLASS_LEAD_RE = re.compile(r"^\s*(\d{1,2})\b")  # e.g. "10 PHYSICS FOUNDATION"


def _connect():
    kwargs = dict(
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    if DB_SOCKET:
        kwargs["unix_socket"] = DB_SOCKET
    else:
        kwargs["host"] = DB_HOST
        kwargs["port"] = DB_PORT
    return pymysql.connect(**kwargs)


def estimate_difficulty(stem: str, question_type: str = "") -> str:
    """Heuristic per-question difficulty (Easy | Moderate | Difficult).

    The bank has no difficulty column, so we estimate from content signals:
    length, presence of formulas, and the question type.  Approximate, but gives
    the adaptive engine a per-question attribute to calibrate against.
    """
    s = stem or ""
    qt = (question_type or "").lower()
    score = 0
    n = len(s)
    if n > 260:
        score += 2
    elif n > 130:
        score += 1
    if "<math" in s or "$" in s or "\\(" in s or "\\frac" in s:
        score += 1
    if any(t in qt for t in ("numerical", "problem", "hots", "assertion", "matrix")):
        score += 1
    if any(t in qt for t in ("definition", "fill", "true", "one word", "short")):
        score -= 1
    if score >= 3:
        return "Difficult"
    if score >= 1:
        return "Moderate"
    return "Easy"


def derive_attributes(book_slug: str) -> Dict[str, str]:
    """subject/class/board inferred from a book_slug.

    Mirror of ``app_server.guess_attributes_from_name`` (kept self-contained to
    avoid a circular import).
    """
    low = (book_slug or "").lower()
    subject = ""
    for s in SUBJECTS:
        if s.lower() in low:
            subject = s
            break
    if not subject and "math" in low:  # "Maths" -> Mathematics
        subject = "Mathematics"
    cls = ""
    m = _CLASS_RE.search(low) or _CLASS_TH_RE.search(low) or _CLASS_LEAD_RE.match(low)
    if m:
        cls = m.group(1)
    board = "Foundation" if "foundation" in low else ""
    return {"subject": subject, "class": cls, "board": board}


# ---------------------------------------------------------------------------
# Filter normalization
# ---------------------------------------------------------------------------
def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_filters(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a loose request dict into a validated filter dict.

    Accepts list values (already split) or scalars for the multi-value keys.
    """
    def lst(key: str) -> List[str]:
        v = raw.get(key)
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip() != ""]

    q = str(raw.get("q") or "").strip()
    sort = str(raw.get("sort") or "")
    if sort not in SORTS:
        sort = "relevance" if q else "newest"

    page = max(1, _int(raw.get("page"), 1))
    page_size = min(PAGE_SIZE_MAX, max(1, _int(raw.get("pageSize"), PAGE_SIZE_DEFAULT)))

    return {
        "subject": lst("subject"),
        "class": lst("class"),
        "board": lst("board"),
        "type": lst("type"),
        "book": lst("book"),
        "chapter": [int(x) for x in lst("chapter") if str(x).isdigit()],
        "q": q,
        "sort": sort,
        "page": page,
        "pageSize": page_size,
    }


# ---------------------------------------------------------------------------
# WHERE construction
# ---------------------------------------------------------------------------
def _slug_attr_map(cur) -> Dict[str, Dict[str, str]]:
    cur.execute("SELECT DISTINCT book_slug FROM qa_content_row")
    return {r["book_slug"]: derive_attributes(r["book_slug"]) for r in cur.fetchall()}


def _allowed_slugs(
    slug_attrs: Dict[str, Dict[str, str]],
    f: Dict[str, Any],
    exclude: frozenset,
) -> Optional[List[str]]:
    """Resolve the slug-level constraints (subject/class/board/book) to a list
    of allowed ``book_slug`` values.

    Returns ``None`` when no slug-level constraint is active (caller should then
    omit the ``book_slug IN (...)`` clause entirely).
    """
    constraints: List[set] = []
    if "subject" not in exclude and f["subject"]:
        want = set(f["subject"])
        constraints.append({s for s, a in slug_attrs.items() if a["subject"] in want})
    if "class" not in exclude and f["class"]:
        want = set(f["class"])
        constraints.append({s for s, a in slug_attrs.items() if a["class"] in want})
    if "board" not in exclude and f["board"]:
        want = set(f["board"])
        constraints.append({s for s, a in slug_attrs.items() if a["board"] in want})
    if "book" not in exclude and f["book"]:
        want = set(f["book"])
        constraints.append({s for s in slug_attrs if s in want})

    if not constraints:
        return None
    allowed = set(slug_attrs.keys())
    for c in constraints:
        allowed &= c
    return sorted(allowed)


def _build_where(
    slug_attrs: Dict[str, Dict[str, str]],
    f: Dict[str, Any],
    exclude: frozenset = frozenset(),
) -> Tuple[str, List[Any]]:
    """Build a WHERE body + params.

    ``exclude`` names dimensions whose own selection should NOT constrain the
    query -- used when computing a facet's counts so that selecting one value in
    a group does not zero out the group's other (OR-able) options.  ``q`` is a
    global text filter and is never excluded.
    """
    clauses: List[str] = []
    params: List[Any] = []

    allowed = _allowed_slugs(slug_attrs, f, exclude)
    if allowed is not None:
        if not allowed:
            return "1=0", []
        clauses.append("book_slug IN (%s)" % ",".join(["%s"] * len(allowed)))
        params.extend(allowed)

    if "type" not in exclude and f["type"]:
        clauses.append("question_type IN (%s)" % ",".join(["%s"] * len(f["type"])))
        params.extend(f["type"])

    if "chapter" not in exclude and f["chapter"]:
        clauses.append("chapter_id IN (%s)" % ",".join(["%s"] * len(f["chapter"])))
        params.extend(f["chapter"])

    if f["q"]:
        clauses.append("(question LIKE %s OR answer LIKE %s)")
        like = "%" + f["q"] + "%"
        params.extend([like, like])

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


# ---------------------------------------------------------------------------
# Read-model mapping
# ---------------------------------------------------------------------------
def _to_summary(r: Dict[str, Any], slug_attrs: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    slug = r["book_slug"]
    attrs = slug_attrs.get(slug) or derive_attributes(slug)
    answer = r.get("answer")
    return {
        "id": r["id"],
        "stem": r.get("question") or "",
        "question_type": r.get("question_type") or "",
        "chapter_id": r.get("chapter_id"),
        "chapter_name": r.get("chapter_name") or "",
        "book_slug": slug,
        "subject": attrs["subject"],
        "class": attrs["class"],
        "board": attrs["board"],
        "has_answer": bool(answer and str(answer).strip()),
        "difficulty": estimate_difficulty(r.get("question"), r.get("question_type")),
        "updated_at": r.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------
def _facet_column(cur, slug_attrs, f, dim: str, col: str) -> List[Dict[str, Any]]:
    where, params = _build_where(slug_attrs, f, exclude=frozenset({dim}))
    cur.execute(
        f"SELECT {col} AS value, COUNT(*) AS count FROM qa_content_row "
        f"WHERE {where} GROUP BY {col} ORDER BY {col}",
        params,
    )
    return [
        {"value": row["value"], "count": int(row["count"])}
        for row in cur.fetchall()
        if row["value"] not in (None, "")
    ]


def _facet_chapter(cur, slug_attrs, f) -> List[Dict[str, Any]]:
    where, params = _build_where(slug_attrs, f, exclude=frozenset({"chapter"}))
    cur.execute(
        "SELECT chapter_id AS value, MAX(chapter_name) AS label, COUNT(*) AS count "
        "FROM qa_content_row WHERE " + where +
        " GROUP BY chapter_id ORDER BY chapter_id",
        params,
    )
    return [
        {"value": row["value"], "label": row["label"] or "", "count": int(row["count"])}
        for row in cur.fetchall()
        if row["value"] is not None
    ]


def _facet_derived(cur, slug_attrs, f, dim: str) -> List[Dict[str, Any]]:
    where, params = _build_where(slug_attrs, f, exclude=frozenset({dim}))
    cur.execute(
        "SELECT book_slug AS slug, COUNT(*) AS count FROM qa_content_row "
        "WHERE " + where + " GROUP BY book_slug",
        params,
    )
    agg: Dict[str, int] = {}
    for row in cur.fetchall():
        attrs = slug_attrs.get(row["slug"]) or derive_attributes(row["slug"])
        val = attrs[dim]
        if not val:
            continue
        agg[val] = agg.get(val, 0) + int(row["count"])
    return [{"value": k, "count": v} for k, v in sorted(agg.items())]


def _compute_facets(cur, slug_attrs, f) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "subject": _facet_derived(cur, slug_attrs, f, "subject"),
        "class": _facet_derived(cur, slug_attrs, f, "class"),
        "board": _facet_derived(cur, slug_attrs, f, "board"),
        "type": _facet_column(cur, slug_attrs, f, "type", "question_type"),
        "book": _facet_column(cur, slug_attrs, f, "book", "book_slug"),
        "chapter": _facet_chapter(cur, slug_attrs, f),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def search_items(raw_filters: Dict[str, Any]) -> Dict[str, Any]:
    """Filtered, paginated item list + facet counts."""
    f = normalize_filters(raw_filters)
    with _connect() as conn:
        with conn.cursor() as cur:
            slug_attrs = _slug_attr_map(cur)
            where, params = _build_where(slug_attrs, f)

            cur.execute("SELECT COUNT(*) AS n FROM qa_content_row WHERE " + where, params)
            total = int(cur.fetchone()["n"])

            offset = (f["page"] - 1) * f["pageSize"]
            cur.execute(
                "SELECT id, chapter_id, book_slug, chapter_name, question, answer, "
                "question_type, updated_at FROM qa_content_row WHERE " + where +
                " ORDER BY " + SORTS[f["sort"]] + " LIMIT %s OFFSET %s",
                params + [f["pageSize"], offset],
            )
            rows = cur.fetchall()

            facets = _compute_facets(cur, slug_attrs, f)

    return {
        "items": [_to_summary(r, slug_attrs) for r in rows],
        "total": total,
        "page": f["page"],
        "pageSize": f["pageSize"],
        "sort": f["sort"],
        "facets": facets,
    }


def compute_facets(raw_filters: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Facet counts only (for refreshing the facet panel independently)."""
    f = normalize_filters(raw_filters)
    with _connect() as conn:
        with conn.cursor() as cur:
            slug_attrs = _slug_attr_map(cur)
            return _compute_facets(cur, slug_attrs, f)


def get_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Single-item detail, or ``None`` if not found."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, chapter_id, book_slug, chapter_name, question, answer, "
                "question_type, created_at, updated_at FROM qa_content_row WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "SELECT chapter_id, chapter_number, chapter_name, page_range, book_slug "
                "FROM qa_chapter WHERE chapter_id = %s",
                (row["chapter_id"],),
            )
            chapter = cur.fetchone()

    attrs = derive_attributes(row["book_slug"])
    answer = row.get("answer")
    return {
        "item": {
            "id": row["id"],
            "stem": row.get("question") or "",
            "answer": answer or "",
            "question_type": row.get("question_type") or "",
            "has_answer": bool(answer and str(answer).strip()),
            "chapter_id": row.get("chapter_id"),
            "chapter_name": row.get("chapter_name") or "",
            "book_slug": row["book_slug"],
            "subject": attrs["subject"],
            "class": attrs["class"],
            "board": attrs["board"],
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        },
        "chapter": chapter,
        "source": {
            "book_slug": row["book_slug"],
            "chapter_id": row.get("chapter_id"),
            "row_id": row["id"],
        },
    }


def health() -> Dict[str, Any]:
    """DB reachability + total item count.  Never raises -- reports db_ok=False
    so the frontend can render a 'bank unreachable' state instead of erroring."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM qa_content_row")
                total = int(cur.fetchone()["n"])
        return {"db_ok": True, "total_items": total}
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"db_ok": False, "error": str(exc)}
