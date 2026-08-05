#!/usr/bin/env python3
"""Practice Engine -- the six PRD practice modes plus Chapter Tests.

    Topic     10-15 Q   focus a single concept
    Chapter   25-40 Q   consolidate a chapter, mixed difficulty
    Mixed     20 Q      revision across chapters, weighted to weak ones
    Sprint    10 Q/5min speed under time pressure
    Adaptive  15-20 Q   difficulty tracks running accuracy
    Mistake   variable  only previously incorrect / skipped questions

Questions come from the MySQL bank, converted to gradable MCQs by
``generators.questions.mcq_parser``.  Sessions are **file-backed** (JSON beside
``exams.json``) so practice works exactly like the rest of the assessment
package -- and, like it, correct answers never reach the client before the
question is answered.

The bank import is lazy: importing this module must not require MySQL.  When the
DB is unreachable, ``start_session`` raises ``PracticeUnavailable`` and callers
degrade instead of crashing.
"""

from __future__ import annotations

import random
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from .storage import _LOCK, _load, _save, get_user

# ---------------------------------------------------------------------------
# Mode configuration -- sizes come straight from the PRD's Practice Modes table.
# ---------------------------------------------------------------------------
MODES: Dict[str, Dict[str, Any]] = {
    "topic": {
        "label": "Topic Practice",
        "purpose": "Reinforce a single concept",
        "default": 12, "min": 5, "max": 15,
        "needs": "chapter",
    },
    "chapter": {
        "label": "Chapter Practice",
        "purpose": "Consolidate an entire chapter",
        "default": 30, "min": 10, "max": 40,
        "needs": "chapter",
    },
    "mixed": {
        "label": "Mixed Practice",
        "purpose": "Revision across chapters",
        "default": 20, "min": 10, "max": 20,
        "needs": "",
    },
    "sprint": {
        "label": "Timed Sprint",
        "purpose": "Improve speed",
        "default": 10, "min": 10, "max": 10,
        "time_limit_sec": 300,
        "needs": "",
    },
    "adaptive": {
        "label": "Adaptive Practice",
        "purpose": "Personalized learning",
        "default": 18, "min": 15, "max": 20,
        "needs": "",
    },
    "mistake": {
        "label": "Mistake Practice",
        "purpose": "Retry previous errors",
        "default": 20, "min": 1, "max": 40,
        "needs": "",
    },
    # The PRD's Daily Challenge -- a fixed 5-question reward quiz.  It selects
    # like Mixed Practice but needs its own entry: Mixed's 10-question floor
    # would otherwise clamp the challenge up to twice its intended size.
    "daily": {
        "label": "Daily Challenge",
        "purpose": "Daily habit building",
        "default": 5, "min": 5, "max": 5,
        "needs": "",
    },
    # Not a practice mode -- the PRD's Chapter Test, which shares this
    # machinery but reports a mastery score.
    "chapter_test": {
        "label": "Chapter Test",
        "purpose": "End of chapter evaluation",
        "default": 20, "min": 5, "max": 40,
        "needs": "chapter",
        "is_test": True,
    },
}

DIFFICULTY_ORDER = ("Easy", "Moderate", "Difficult")

# PRD "Chapter Test -> Mastery score" bands.
MASTERY_BANDS = (
    (85, "Mastered"),
    (70, "Proficient"),
    (50, "Developing"),
    (0, "Needs Work"),
)

# Mixed/Chapter practice difficulty blend (easy, moderate, difficult).
_BLEND = {"Easy": 0.35, "Moderate": 0.45, "Difficult": 0.20}


class PracticeUnavailable(RuntimeError):
    """Raised when the question bank cannot be reached or has too few rows."""


# ---------------------------------------------------------------------------
# Bank access (lazy -- importing this module must not require MySQL)
# ---------------------------------------------------------------------------
_SELECT = """
SELECT id, chapter_id, chapter_name, book_slug, question, answer, question_type,
       difficulty, subtopic, cognitive_level, learning_objective
  FROM qa_content_row
"""


def _fetch_rows(where: str = "", params: Sequence[Any] = (), cap: int = 1200) -> List[Dict[str, Any]]:
    from edu_pipeline.storage.database import _connect

    sql = _SELECT + (f" WHERE {where}" if where else "") + " LIMIT %s"
    cn = _connect()
    try:
        with cn.cursor() as cur:
            cur.execute(sql, tuple(params) + (cap,))
            return list(cur.fetchall())
    finally:
        cn.close()


def _gradable(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from edu_pipeline.generators.questions.mcq_parser import to_mcqs

    return to_mcqs(rows)


def bank_health() -> Dict[str, Any]:
    """Whether practice can run, and how much of the bank is gradable."""
    try:
        rows = _fetch_rows(cap=400)
    except Exception as exc:  # pragma: no cover - depends on live MySQL
        return {"ok": False, "error": str(exc), "sampled": 0, "gradable": 0}
    good = _gradable(rows)
    return {
        "ok": bool(good),
        "error": "" if good else "no auto-gradable questions found",
        "sampled": len(rows),
        "gradable": len(good),
    }


def list_chapters(book_slug: str = "", min_questions: int = 5) -> List[Dict[str, Any]]:
    """Chapters that hold enough gradable questions to practise against."""
    where, params = ("book_slug = %s", [book_slug]) if book_slug else ("", [])
    rows = _fetch_rows(where, params, cap=20000)
    by_chapter: Dict[Any, Dict[str, Any]] = {}
    for m in _gradable(rows):
        c = by_chapter.setdefault(
            m["chapter_id"],
            {
                "chapter_id": m["chapter_id"],
                "chapter_name": m["chapter_name"],
                "book_slug": m["book_slug"],
                "count": 0,
                "subtopics": set(),
            },
        )
        c["count"] += 1
        if m["subtopic"]:
            c["subtopics"].add(m["subtopic"])

    out = []
    for c in by_chapter.values():
        if c["count"] < min_questions:
            continue
        c["subtopics"] = sorted(c["subtopics"])
        out.append(c)
    out.sort(key=lambda c: (c["book_slug"], str(c["chapter_name"])))
    return out


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def _blend_pick(pool: List[Dict[str, Any]], total: int, rng: random.Random) -> List[Dict[str, Any]]:
    """Pick ``total`` questions spread across difficulty per ``_BLEND``.

    Shortfalls in one band are backfilled from the others so the caller still
    gets a full-length session when the bank is thin at one difficulty.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {d: [] for d in DIFFICULTY_ORDER}
    for q in pool:
        buckets.setdefault(q.get("difficulty") or "Moderate", buckets["Moderate"]).append(q)
    for b in buckets.values():
        rng.shuffle(b)

    picked: List[Dict[str, Any]] = []
    for level in DIFFICULTY_ORDER:
        want = int(round(total * _BLEND[level]))
        picked.extend(buckets[level][:want])

    if len(picked) < total:
        chosen = {id(q) for q in picked}
        rest = [q for q in pool if id(q) not in chosen]
        rng.shuffle(rest)
        picked.extend(rest[: total - len(picked)])

    rng.shuffle(picked)
    return picked[:total]


def _weak_chapters(uid: str, limit: int = 6) -> List[Any]:
    """Chapter ids the student performs worst on, worst first."""
    stats = history(uid).get("per_chapter", {})
    ranked = sorted(
        (c for c in stats.values() if c["answered"] >= 3),
        key=lambda c: c["accuracy"],
    )
    return [c["chapter_id"] for c in ranked[:limit]]


def select_questions(
    mode: str,
    uid: str = "",
    chapter_id: Any = None,
    subtopic: str = "",
    book_slug: str = "",
    total: Optional[int] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Choose the question set for a session according to the mode's rules."""
    cfg = MODES.get(mode)
    if not cfg:
        raise ValueError(f"Unknown practice mode: {mode}")

    n = int(total or cfg["default"])
    n = max(cfg["min"], min(cfg["max"], n))
    rng = random.Random(seed)

    if mode == "mistake":
        return _mistake_pool(uid, n, rng)

    where: List[str] = []
    params: List[Any] = []
    if chapter_id is not None:
        where.append("chapter_id = %s")
        params.append(chapter_id)
    if book_slug:
        where.append("book_slug = %s")
        params.append(book_slug)
    if subtopic:
        where.append("subtopic = %s")
        params.append(subtopic)

    if mode in ("mixed", "daily") and uid and chapter_id is None:
        weak = _weak_chapters(uid)
        if weak:
            where.append("chapter_id IN (" + ",".join(["%s"] * len(weak)) + ")")
            params.extend(weak)

    pool = _gradable(_fetch_rows(" AND ".join(where), params, cap=4000))
    if not pool:
        raise PracticeUnavailable("No auto-gradable questions match that selection.")

    if mode == "sprint":
        # Speed drill -- bias to quick questions, shortest stems first.
        pool = [q for q in pool if q["difficulty"] in ("Easy", "Moderate")] or pool
        pool.sort(key=lambda q: len(q["stem"]))
        head = pool[: max(n * 3, n)]
        rng.shuffle(head)
        return head[:n]

    if mode == "adaptive":
        # Serve the full spread; difficulty is steered per answer at runtime.
        return _blend_pick(pool, n, rng)

    if mode == "topic":
        rng.shuffle(pool)
        return pool[:n]

    return _blend_pick(pool, n, rng)


def _mistake_pool(uid: str, n: int, rng: random.Random) -> List[Dict[str, Any]]:
    """Re-serve the questions this student got wrong or skipped."""
    ids = history(uid).get("mistake_ids", [])
    if not ids:
        raise PracticeUnavailable("No past mistakes yet — finish a practice session first.")
    ids = ids[: max(n, 1) * 2]
    placeholders = ",".join(["%s"] * len(ids))
    pool = _gradable(_fetch_rows(f"id IN ({placeholders})", ids, cap=len(ids)))
    if not pool:
        raise PracticeUnavailable("Past mistakes are no longer available in the bank.")
    rng.shuffle(pool)
    return pool[:n]


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _sessions() -> Dict[str, Any]:
    return _load("practice", {"sessions": {}})


def _write(data: Dict[str, Any]) -> None:
    _save("practice", data)


def public_session(s: Dict[str, Any], reveal: bool = False) -> Dict[str, Any]:
    """Client-safe view.  ``correct_index`` is withheld until the session ends."""
    qs = []
    for i, q in enumerate(s["questions"]):
        item = {
            "index": i,
            "stem": q["stem"],
            "options": q["options"],
            "difficulty": q["difficulty"],
            "cognitive_level": q["cognitive_level"],
            "subtopic": q["subtopic"],
            "chapter_name": q["chapter_name"],
            "source_id": q["source_id"],
        }
        if reveal:
            item["correct_index"] = q["correct_index"]
            item["learning_objective"] = q["learning_objective"]
            item["answer_text"] = q.get("answer_text", "")
        qs.append(item)
    return {
        "id": s["id"],
        "mode": s["mode"],
        "label": MODES.get(s["mode"], {}).get("label", s["mode"]),
        "status": s["status"],
        "chapter_id": s.get("chapter_id"),
        "chapter_name": s.get("chapter_name", ""),
        "subtopic": s.get("subtopic", ""),
        "total": len(s["questions"]),
        "answered": sum(1 for a in s["answers"] if a is not None),
        "time_limit_sec": s.get("time_limit_sec", 0),
        "started_at": s["started_at"],
        "questions": qs,
    }


def start_session(
    user: Dict[str, Any],
    mode: str,
    chapter_id: Any = None,
    subtopic: str = "",
    book_slug: str = "",
    total: Optional[int] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a practice session and return its client-safe view."""
    cfg = MODES.get(mode)
    if not cfg:
        raise ValueError(f"Unknown practice mode: {mode}")
    if cfg.get("needs") == "chapter" and chapter_id is None:
        raise ValueError(f"{cfg['label']} needs a chapter.")

    questions = select_questions(
        mode, uid=user["id"], chapter_id=chapter_id, subtopic=subtopic,
        book_slug=book_slug, total=total, seed=seed,
    )
    if not questions:
        raise PracticeUnavailable("Could not assemble a question set.")

    now = int(time.time())
    session = {
        "id": "ps_" + uuid.uuid4().hex[:12],
        "uid": user["id"],
        "mode": mode,
        "status": "active",
        "chapter_id": chapter_id,
        "chapter_name": questions[0].get("chapter_name", ""),
        "subtopic": subtopic,
        "book_slug": book_slug,
        "questions": questions,
        "answers": [None] * len(questions),
        "times": [0] * len(questions),
        "started_at": now,
        "last_at": now,
        "finished_at": 0,
        "time_limit_sec": int(cfg.get("time_limit_sec", 0)),
    }
    with _LOCK:
        data = _sessions()
        data["sessions"][session["id"]] = session
        _write(data)
    return public_session(session)


def get_session(uid: str, sid: str) -> Optional[Dict[str, Any]]:
    s = _sessions()["sessions"].get(sid)
    if not s or s["uid"] != uid:
        return None
    return s


def answer(uid: str, sid: str, index: int, choice: Optional[int], time_sec: int = 0) -> Dict[str, Any]:
    """Record one answer.  ``choice`` of ``None`` means skipped.

    Returns immediate per-question feedback (practice is formative, so the
    correct option is revealed straight away) plus the adaptive engine's
    suggested next difficulty.
    """
    with _LOCK:
        data = _sessions()
        s = data["sessions"].get(sid)
        if not s or s["uid"] != uid:
            raise ValueError("Session not found.")
        if s["status"] != "active":
            raise ValueError("Session already finished.")
        if not (0 <= index < len(s["questions"])):
            raise ValueError("Question index out of range.")

        q = s["questions"][index]
        s["answers"][index] = choice
        s["times"][index] = max(0, int(time_sec))
        s["last_at"] = int(time.time())
        _write(data)

    is_correct = choice is not None and int(choice) == q["correct_index"]
    return {
        "index": index,
        "chosen_index": choice,
        "is_correct": is_correct,
        "correct_index": q["correct_index"],
        "answer_text": q.get("answer_text", ""),
        "learning_objective": q["learning_objective"],
        "next_difficulty": _next_difficulty(s),
        "answered": sum(1 for a in s["answers"] if a is not None),
        "total": len(s["questions"]),
    }


def _next_difficulty(s: Dict[str, Any]) -> str:
    """Adaptive step: raise difficulty on a hot streak, lower it on a cold one.

    Uses the last five graded answers so the level tracks current form rather
    than the whole session average.
    """
    graded = [
        (a == s["questions"][i]["correct_index"])
        for i, a in enumerate(s["answers"])
        if a is not None
    ]
    if not graded:
        return "Moderate"
    window = graded[-5:]
    acc = sum(window) / len(window)
    if acc >= 0.8:
        return "Difficult"
    if acc <= 0.4:
        return "Easy"
    return "Moderate"


def finish(uid: str, sid: str) -> Dict[str, Any]:
    """Close a session and return the PRD Result Analysis report."""
    with _LOCK:
        data = _sessions()
        s = data["sessions"].get(sid)
        if not s or s["uid"] != uid:
            raise ValueError("Session not found.")
        if s["status"] == "active":
            s["status"] = "finished"
            s["finished_at"] = int(time.time())
            _write(data)
    return report(s)


def report(s: Dict[str, Any]) -> Dict[str, Any]:
    """Result Analysis: overall, per-topic, per-difficulty, per-Bloom-level,
    time per question, and the mistakes worth revising.
    """
    questions, answers, times = s["questions"], s["answers"], s["times"]
    correct = incorrect = skipped = 0
    per_topic: Dict[str, Dict[str, Any]] = {}
    per_difficulty: Dict[str, Dict[str, Any]] = {}
    per_cognitive: Dict[str, Dict[str, Any]] = {}
    detail: List[Dict[str, Any]] = []
    mistakes: List[Dict[str, Any]] = []

    def bucket(d: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
        return d.setdefault(key or "—", {"correct": 0, "answered": 0, "total": 0})

    for i, q in enumerate(questions):
        chosen = answers[i]
        ok = chosen is not None and int(chosen) == q["correct_index"]
        topic = q["subtopic"] or q["chapter_name"] or "—"

        for d, key in ((per_topic, topic), (per_difficulty, q["difficulty"]),
                       (per_cognitive, q["cognitive_level"])):
            b = bucket(d, key)
            b["total"] += 1
            if chosen is not None:
                b["answered"] += 1
                if ok:
                    b["correct"] += 1

        if chosen is None:
            skipped += 1
        elif ok:
            correct += 1
        else:
            incorrect += 1

        detail.append({
            "index": i, "source_id": q["source_id"], "stem": q["stem"],
            "options": q["options"], "chosen": chosen,
            "correct_index": q["correct_index"], "is_correct": ok if chosen is not None else None,
            "difficulty": q["difficulty"], "cognitive_level": q["cognitive_level"],
            "subtopic": q["subtopic"], "chapter_name": q["chapter_name"],
            "learning_objective": q["learning_objective"], "time_sec": times[i],
            "answer_text": q.get("answer_text", ""),
        })
        if not ok:
            mistakes.append({
                "source_id": q["source_id"], "stem": q["stem"], "subtopic": q["subtopic"],
                "chapter_id": q["chapter_id"], "chapter_name": q["chapter_name"],
                "difficulty": q["difficulty"], "skipped": chosen is None,
            })

    for d in (per_topic, per_difficulty, per_cognitive):
        for b in d.values():
            b["accuracy"] = round(100 * b["correct"] / b["answered"], 1) if b["answered"] else 0.0

    total = len(questions)
    attempted = correct + incorrect
    accuracy = round(100 * correct / attempted, 1) if attempted else 0.0
    score_pct = round(100 * correct / total, 1) if total else 0.0
    spent = sum(times)

    out = {
        "session_id": s["id"],
        "mode": s["mode"],
        "label": MODES.get(s["mode"], {}).get("label", s["mode"]),
        "chapter_id": s.get("chapter_id"),
        "chapter_name": s.get("chapter_name", ""),
        "status": s["status"],
        "counts": {"total": total, "correct": correct, "incorrect": incorrect,
                   "skipped": skipped, "attempted": attempted},
        "accuracy": accuracy,
        "score_pct": score_pct,
        "time_spent_sec": spent,
        "avg_time_sec": round(spent / total, 1) if total else 0.0,
        "per_topic": per_topic,
        "per_difficulty": per_difficulty,
        "per_cognitive_level": per_cognitive,
        "questions": detail,
        "mistakes": mistakes,
        "started_at": s["started_at"],
        "finished_at": s.get("finished_at", 0),
    }

    if MODES.get(s["mode"], {}).get("is_test"):
        out["mastery"] = mastery(score_pct)
    out["recommendation"] = _recommendation(out)
    return out


def mastery(score_pct: float) -> Dict[str, Any]:
    """PRD Chapter Test outcome -- a mastery score with a named band."""
    for floor, label in MASTERY_BANDS:
        if score_pct >= floor:
            return {"score": score_pct, "band": label, "passed": score_pct >= 50}
    return {"score": score_pct, "band": "Needs Work", "passed": False}


def _recommendation(rep: Dict[str, Any]) -> Dict[str, str]:
    """The PRD's 'recommend next learning activity' line for a finished set."""
    acc = rep["accuracy"]
    weak = sorted(
        (t for t, b in rep["per_topic"].items() if b["answered"] >= 2),
        key=lambda t: rep["per_topic"][t]["accuracy"],
    )
    weakest = weak[0] if weak else ""

    if rep["counts"]["attempted"] == 0:
        return {"action": "retry", "mode": rep["mode"],
                "text": "Nothing was attempted — try the set again."}
    if acc >= 85:
        return {"action": "advance", "mode": "chapter_test",
                "text": "Strong result. Take the Chapter Test to lock in mastery."}
    if acc < 50:
        return {"action": "revise", "mode": "topic",
                "text": f"Revise {weakest or 'this chapter'} before practising further."}
    if rep["mistakes"]:
        return {"action": "mistake_practice", "mode": "mistake",
                "text": f"Retry your {len(rep['mistakes'])} missed question(s) in Mistake Practice."}
    return {"action": "continue", "mode": "chapter",
            "text": "Good progress — continue with Chapter Practice."}


# ---------------------------------------------------------------------------
# History (feeds Mixed/Mistake modes, the dashboard and analytics)
# ---------------------------------------------------------------------------
def list_sessions(uid: str, limit: int = 50) -> List[Dict[str, Any]]:
    out = [s for s in _sessions()["sessions"].values() if s["uid"] == uid]
    out.sort(key=lambda s: s["started_at"], reverse=True)
    return [
        {
            "id": s["id"], "mode": s["mode"],
            "label": MODES.get(s["mode"], {}).get("label", s["mode"]),
            "status": s["status"], "chapter_id": s.get("chapter_id"),
            "chapter_name": s.get("chapter_name", ""),
            "total": len(s["questions"]),
            "answered": sum(1 for a in s["answers"] if a is not None),
            "started_at": s["started_at"], "finished_at": s.get("finished_at", 0),
        }
        for s in out[:limit]
    ]


def history(uid: str) -> Dict[str, Any]:
    """Aggregate practice history for one student.

    ``mistake_ids`` is ordered most-recent-first and excludes questions the
    student has since answered correctly, so Mistake Practice does not keep
    re-serving something already fixed.
    """
    sessions = [s for s in _sessions()["sessions"].values() if s["uid"] == uid]
    sessions.sort(key=lambda s: s["started_at"])

    per_chapter: Dict[Any, Dict[str, Any]] = {}
    per_topic: Dict[str, Dict[str, Any]] = {}
    wrong: Dict[Any, int] = {}
    fixed: set = set()
    total_q = total_correct = total_time = 0
    active_days: set = set()

    for s in sessions:
        active_days.add(time.strftime("%Y-%m-%d", time.localtime(s["started_at"])))
        finished = s["status"] == "finished"
        for i, q in enumerate(s["questions"]):
            chosen = s["answers"][i]
            if chosen is None:
                # A skip only counts once the student has actually been through
                # the set.  Untouched questions in an abandoned session were
                # never seen, so they must not enter the mistake queue.
                if finished:
                    wrong[q["source_id"]] = s["started_at"]
                continue
            ok = int(chosen) == q["correct_index"]
            total_q += 1
            total_correct += int(ok)
            total_time += s["times"][i]

            c = per_chapter.setdefault(q["chapter_id"], {
                "chapter_id": q["chapter_id"], "chapter_name": q["chapter_name"],
                "answered": 0, "correct": 0,
            })
            c["answered"] += 1
            c["correct"] += int(ok)

            key = q["subtopic"] or q["chapter_name"] or "—"
            t = per_topic.setdefault(key, {"topic": key, "answered": 0, "correct": 0})
            t["answered"] += 1
            t["correct"] += int(ok)

            if ok:
                fixed.add(q["source_id"])
                wrong.pop(q["source_id"], None)
            else:
                wrong[q["source_id"]] = s["started_at"]
                fixed.discard(q["source_id"])

    for d in (per_chapter, per_topic):
        for b in d.values():
            b["accuracy"] = round(100 * b["correct"] / b["answered"], 1) if b["answered"] else 0.0

    mistake_ids = [qid for qid, _ts in sorted(wrong.items(), key=lambda kv: kv[1], reverse=True)]

    return {
        "sessions": len(sessions),
        "finished": sum(1 for s in sessions if s["status"] == "finished"),
        "questions_answered": total_q,
        "correct": total_correct,
        "accuracy": round(100 * total_correct / total_q, 1) if total_q else 0.0,
        "time_spent_sec": total_time,
        "per_chapter": per_chapter,
        "per_topic": per_topic,
        "mistake_ids": mistake_ids,
        "mistake_count": len(mistake_ids),
        "active_days": sorted(active_days),
        "last_session_at": sessions[-1]["started_at"] if sessions else 0,
        "last_chapter_id": sessions[-1].get("chapter_id") if sessions else None,
        "last_chapter_name": sessions[-1].get("chapter_name", "") if sessions else "",
    }


def modes_catalog() -> List[Dict[str, Any]]:
    """Mode metadata for the UI (label, purpose, size, whether it needs input)."""
    return [
        {
            "mode": k,
            "label": v["label"],
            "purpose": v["purpose"],
            "size": v["default"],
            "min": v["min"],
            "max": v["max"],
            "needs_chapter": v.get("needs") == "chapter",
            "time_limit_sec": int(v.get("time_limit_sec", 0)),
            "is_test": bool(v.get("is_test")),
        }
        for k, v in MODES.items()
    ]


def require_student(uid: str) -> Dict[str, Any]:
    u = get_user(uid)
    if not u:
        raise ValueError("Unknown user.")
    return u
