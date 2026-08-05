#!/usr/bin/env python3
"""Student dashboard -- the PRD's six command-centre widgets.

    Daily Goal          today's study target and progress
    Continue Learning   resume the last chapter (only while progress < 100%)
    Daily Challenge     a 5-question reward quiz that resets every day
    AI Recommendation   next chapter or revision, derived from performance
    Weekly Progress     the seven-day learning trend
    Saved Content       recent snippets and bookmarks

Each widget is computed independently and returns its own ``ok`` flag, so one
unavailable data source (MySQL down, Learn module not yet built) degrades that
single card instead of blanking the dashboard -- the PRD's "widgets should load
independently" developer note.

Goal state lives in ``progress.json`` next to the other assessment files.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from . import practice
from .storage import _LOCK, _load, _save

DEFAULT_DAILY_GOAL = 20          # questions/day
DAILY_CHALLENGE_SIZE = 5
CHAPTER_COMPLETE_AT = 100        # % of a chapter's questions seen


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _day_of(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# ---------------------------------------------------------------------------
# Per-student progress record
# ---------------------------------------------------------------------------
def _progress() -> Dict[str, Any]:
    return _load("progress", {"students": {}})


def get_progress(uid: str) -> Dict[str, Any]:
    rec = _progress()["students"].get(uid) or {}
    return {
        "daily_goal": int(rec.get("daily_goal", DEFAULT_DAILY_GOAL)),
        "streak": int(rec.get("streak", 0)),
        "best_streak": int(rec.get("best_streak", 0)),
        "last_active_day": rec.get("last_active_day", ""),
        "challenge": rec.get("challenge", {}),
    }


def set_daily_goal(uid: str, goal: int) -> Dict[str, Any]:
    goal = max(5, min(200, int(goal)))
    with _LOCK:
        data = _progress()
        rec = data["students"].setdefault(uid, {})
        rec["daily_goal"] = goal
        _save("progress", data)
    return get_progress(uid)


def _recompute_streak(uid: str, active_days: List[str]) -> Dict[str, int]:
    """Consecutive-day streak ending today or yesterday.

    A streak survives until a day is fully missed: practising today continues
    yesterday's run, and a gap of two or more days resets it to zero.
    """
    if not active_days:
        return {"streak": 0, "best_streak": 0}

    days = sorted(set(active_days))
    best = run = 1
    for prev, cur in zip(days, days[1:], strict=False):
        prev_t = time.mktime(time.strptime(prev, "%Y-%m-%d"))
        cur_t = time.mktime(time.strptime(cur, "%Y-%m-%d"))
        run = run + 1 if round((cur_t - prev_t) / 86400) == 1 else 1
        best = max(best, run)

    today = _today()
    last = days[-1]
    gap = round(
        (time.mktime(time.strptime(today, "%Y-%m-%d"))
         - time.mktime(time.strptime(last, "%Y-%m-%d"))) / 86400
    )
    current = run if gap <= 1 else 0

    with _LOCK:
        data = _progress()
        rec = data["students"].setdefault(uid, {})
        rec["streak"] = current
        rec["best_streak"] = max(best, int(rec.get("best_streak", 0)))
        rec["last_active_day"] = last
        _save("progress", data)
        return {"streak": current, "best_streak": rec["best_streak"]}


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
def widget_daily_goal(uid: str, hist: Dict[str, Any]) -> Dict[str, Any]:
    """Today's target and how far through it the student is."""
    prog = get_progress(uid)
    goal = prog["daily_goal"]
    today = _today()

    done = 0
    for s in practice._sessions()["sessions"].values():
        if s["uid"] != uid or _day_of(s["started_at"]) != today:
            continue
        done += sum(1 for a in s["answers"] if a is not None)

    streak = _recompute_streak(uid, hist.get("active_days", []))
    return {
        "ok": True,
        "goal": goal,
        "done": done,
        "remaining": max(0, goal - done),
        "pct": min(100, round(100 * done / goal)) if goal else 0,
        "met": done >= goal,
        "streak": streak["streak"],
        "best_streak": streak["best_streak"],
    }


def widget_continue_learning(uid: str, hist: Dict[str, Any]) -> Dict[str, Any]:
    """Resume the last chapter -- hidden once that chapter is complete."""
    cid = hist.get("last_chapter_id")
    if cid is None:
        return {"ok": True, "show": False, "reason": "no practice yet"}

    stats = hist.get("per_chapter", {}).get(cid) or hist.get("per_chapter", {}).get(str(cid))
    if not stats:
        return {"ok": True, "show": False, "reason": "no answered questions yet"}

    try:
        total = _chapter_question_count(cid)
    except Exception as exc:
        return {"ok": False, "show": False, "error": str(exc)}

    seen = stats["answered"]
    pct = min(100, round(100 * seen / total)) if total else 0
    return {
        "ok": True,
        "show": pct < CHAPTER_COMPLETE_AT,
        "chapter_id": cid,
        "chapter_name": hist.get("last_chapter_name", "") or stats.get("chapter_name", ""),
        "seen": seen,
        "total": total,
        "pct": pct,
        "accuracy": stats["accuracy"],
        "resume_mode": "chapter",
    }


def _chapter_question_count(chapter_id: Any) -> int:
    from edu_pipeline.storage.database import _connect

    cn = _connect()
    try:
        with cn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM qa_content_row WHERE chapter_id = %s",
                (chapter_id,),
            )
            return int(cur.fetchone()["n"])
    finally:
        cn.close()


def widget_daily_challenge(uid: str) -> Dict[str, Any]:
    """A 5-question quiz that resets at midnight."""
    prog = get_progress(uid)
    ch = prog.get("challenge") or {}
    today = _today()

    if ch.get("date") != today:
        return {"ok": True, "date": today, "size": DAILY_CHALLENGE_SIZE,
                "status": "available", "session_id": "", "score": None}

    sid = ch.get("session_id", "")
    sess = practice._sessions()["sessions"].get(sid) if sid else None
    if sess and sess["status"] == "finished":
        rep = practice.report(sess)
        return {"ok": True, "date": today, "size": DAILY_CHALLENGE_SIZE,
                "status": "completed", "session_id": sid,
                "score": rep["counts"]["correct"], "accuracy": rep["accuracy"]}
    return {"ok": True, "date": today, "size": DAILY_CHALLENGE_SIZE,
            "status": "in_progress" if sess else "available",
            "session_id": sid, "score": None}


def start_daily_challenge(user: Dict[str, Any]) -> Dict[str, Any]:
    """Start (or resume) today's challenge -- one per student per day."""
    uid = user["id"]
    state = widget_daily_challenge(uid)
    if state["status"] == "completed":
        raise ValueError("Today's challenge is already complete — come back tomorrow.")
    if state["status"] == "in_progress" and state["session_id"]:
        existing = practice.get_session(uid, state["session_id"])
        if existing:
            return practice.public_session(existing)

    sess = practice.start_session(user, "daily", total=DAILY_CHALLENGE_SIZE)
    with _LOCK:
        data = _progress()
        rec = data["students"].setdefault(uid, {})
        rec["challenge"] = {"date": _today(), "session_id": sess["id"]}
        _save("progress", data)
    return sess


def widget_ai_recommendation(uid: str, hist: Dict[str, Any]) -> Dict[str, Any]:
    """Next best action, derived from measured performance.

    Rule-based on purpose: the PRD wants recommendations a student can trust and
    a teacher can audit, so each one carries the reason it fired.
    """
    if not hist.get("questions_answered"):
        return {"ok": True, "action": "start", "mode": "chapter",
                "title": "Start with Chapter Practice",
                "why": "You have not practised yet — a chapter set will establish your baseline."}

    if hist.get("mistake_count", 0) >= 5:
        return {"ok": True, "action": "mistake_practice", "mode": "mistake",
                "title": f"Clear {hist['mistake_count']} pending mistakes",
                "why": "Retrying missed questions is the fastest way to lift accuracy."}

    weak = sorted(
        (c for c in hist.get("per_chapter", {}).values() if c["answered"] >= 3),
        key=lambda c: c["accuracy"],
    )
    if weak and weak[0]["accuracy"] < 60:
        w = weak[0]
        return {"ok": True, "action": "revise", "mode": "topic",
                "chapter_id": w["chapter_id"], "chapter_name": w["chapter_name"],
                "title": f"Revise {w['chapter_name']}",
                "why": f"Your accuracy there is {w['accuracy']}% — below the 60% mastery line."}

    if hist.get("accuracy", 0) >= 80:
        return {"ok": True, "action": "advance", "mode": "chapter_test",
                "chapter_id": hist.get("last_chapter_id"),
                "title": "Take a Chapter Test",
                "why": f"You are averaging {hist['accuracy']}% — you are ready to be assessed."}

    return {"ok": True, "action": "continue", "mode": "mixed",
            "title": "Mixed Practice across your weak chapters",
            "why": f"Steady at {hist.get('accuracy', 0)}% — mixed revision will consolidate it."}


def widget_weekly_progress(uid: str, days: int = 7) -> Dict[str, Any]:
    """Per-day answered/correct counts for the trailing week."""
    now = time.time()
    buckets: Dict[str, Dict[str, int]] = {}
    for i in range(days - 1, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(now - i * 86400))
        buckets[d] = {"day": d, "answered": 0, "correct": 0, "minutes": 0}

    for s in practice._sessions()["sessions"].values():
        if s["uid"] != uid:
            continue
        d = _day_of(s["started_at"])
        if d not in buckets:
            continue
        b = buckets[d]
        for i, q in enumerate(s["questions"]):
            chosen = s["answers"][i]
            if chosen is None:
                continue
            b["answered"] += 1
            b["correct"] += int(int(chosen) == q["correct_index"])
            b["minutes"] += s["times"][i] / 60.0

    series = []
    for b in buckets.values():
        b["minutes"] = round(b["minutes"], 1)
        b["accuracy"] = round(100 * b["correct"] / b["answered"], 1) if b["answered"] else 0.0
        series.append(b)

    total = sum(b["answered"] for b in series)
    correct = sum(b["correct"] for b in series)
    return {
        "ok": True,
        "series": series,
        "total_answered": total,
        "total_correct": correct,
        "accuracy": round(100 * correct / total, 1) if total else 0.0,
        "active_days": sum(1 for b in series if b["answered"] > 0),
        "minutes": round(sum(b["minutes"] for b in series), 1),
    }


def widget_saved_content(uid: str) -> Dict[str, Any]:
    """Recent snippets and bookmarks.

    The Saved Library is part of the Learn Module (PRD Phase 2) which is not
    built yet, so this reports ``available: False`` rather than inventing data.
    The shape is already the final one, so the widget needs no change when the
    Learn Module lands.
    """
    return {
        "ok": True,
        "available": False,
        "items": [],
        "counts": {"snippets": 0, "bookmarks": 0, "notes": 0},
        "note": "Saved Library arrives with the Learn Module.",
    }


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
def _safe(fn, *args) -> Dict[str, Any]:
    """Run one widget; a failure degrades that card only."""
    try:
        return fn(*args)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def student_dashboard(user: Dict[str, Any]) -> Dict[str, Any]:
    """All six widgets for one student."""
    uid = user["id"]
    try:
        hist = practice.history(uid)
    except Exception as exc:
        hist = {"error": str(exc)}

    return {
        "user": {"id": uid, "name": user.get("name", ""), "role": user.get("role", "student")},
        "widgets": {
            "daily_goal": _safe(widget_daily_goal, uid, hist),
            "continue_learning": _safe(widget_continue_learning, uid, hist),
            "daily_challenge": _safe(widget_daily_challenge, uid),
            "ai_recommendation": _safe(widget_ai_recommendation, uid, hist),
            "weekly_progress": _safe(widget_weekly_progress, uid),
            "saved_content": _safe(widget_saved_content, uid),
        },
        "summary": {
            "questions_answered": hist.get("questions_answered", 0),
            "accuracy": hist.get("accuracy", 0.0),
            "sessions": hist.get("sessions", 0),
            "mistakes": hist.get("mistake_count", 0),
            "time_spent_sec": hist.get("time_spent_sec", 0),
        },
    }
