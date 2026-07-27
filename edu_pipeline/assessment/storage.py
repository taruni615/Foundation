#!/usr/bin/env python3
"""File-backed assessment store (Slice 1: student experience + analytics).

Holds accounts, hosted exams (teacher-keyed MCQs), and student attempts as JSON
under ``assessment/``.  Grading happens server-side so correct answers are never
sent to the client before submission.  Stdlib only — works without MySQL, mirrors
the file-based style of the extraction pipeline.

Not production-hardened auth (pbkdf2 passwords + HMAC bearer tokens) but real
enough for multi-student hosting.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT if (REPO_ROOT / "users.json").is_file() or not (REPO_ROOT / "assessment").is_dir() else (REPO_ROOT / "assessment")
_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Storage primitives
# ---------------------------------------------------------------------------
def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def _load(name: str, default: Any) -> Any:
    p = _path(name)
    if not p.is_file():
        return default
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _save(name: str, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(name).with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(_path(name))


def _secret() -> bytes:
    env = os.environ.get("ASSESS_SECRET")
    if env:
        return env.encode("utf-8")
    sp = DATA_DIR / ".secret"
    if sp.is_file():
        return sp.read_bytes()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s = uuid.uuid4().hex.encode("utf-8") + uuid.uuid4().hex.encode("utf-8")
    sp.write_bytes(s)
    return s


# ---------------------------------------------------------------------------
# Passwords + tokens
# ---------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    iters = 120000
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)
    return f"pbkdf2${iters}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user: Dict[str, Any], ttl_days: int = 30) -> str:
    payload = {"uid": user["id"], "role": user["role"], "iat": int(time.time()), "exp": int(time.time()) + ttl_days * 86400}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        body, sig = token.split(".")
        expected = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def public_user(u: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": u["id"], "name": u.get("name", ""), "username": u["username"], "role": u["role"],
            "roll": u.get("roll", ""), "klass": u.get("klass", ""), "section": u.get("section", "")}


def find_by_username(username: str) -> Optional[Dict[str, Any]]:
    uname = (username or "").strip().lower()
    for u in _load("users", []):
        if u["username"].lower() == uname:
            return u
    return None


def get_user(uid: str) -> Optional[Dict[str, Any]]:
    for u in _load("users", []):
        if u["id"] == uid:
            return u
    return None


def create_user(name: str, username: str, password: str, role: str = "student",
                 roll: str = "", klass: str = "", section: str = "") -> Dict[str, Any]:
    role = "teacher" if role == "teacher" else "student"
    with _LOCK:
        ensure_seed()
        if find_by_username(username):
            raise ValueError("Username already taken")
        users = _load("users", [])
        user = {
            "id": "u_" + uuid.uuid4().hex[:12],
            "name": (name or "").strip(),
            "username": (username or "").strip(),
            "password": hash_password(password),
            "role": role,
            "roll": (roll or "").strip(),
            "klass": (klass or "").strip(),
            "section": (section or "").strip(),
            "created_at": int(time.time()),
        }
        users.append(user)
        _save("users", users)
        return user


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    u = find_by_username(username)
    if u and verify_password(password, u["password"]):
        return u
    return None


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
def exam_phase(exam: Dict[str, Any], now: Optional[int] = None) -> str:
    """draft | upcoming | live | ended — based on status + optional time window."""
    if exam.get("status") != "hosted":
        return "draft"
    now = int(time.time()) if now is None else now
    s, e = exam.get("start_at"), exam.get("end_at")
    if s and now < int(s):
        return "upcoming"
    if e and now > int(e):
        return "ended"
    return "live"


def _strip_answers(exam: Dict[str, Any]) -> Dict[str, Any]:
    """Public exam view for taking — correct_index and the written model answer
    removed so they aren't leaked before submission."""
    out = {k: v for k, v in exam.items() if k != "questions"}
    out["questions"] = [
        {k: v for k, v in q.items() if k not in ("correct_index", "answer")} for q in exam.get("questions", [])
    ]
    return out


def _exam_targets_user(exam: Dict[str, Any], user: Optional[Dict[str, Any]]) -> bool:
    """An exam with no targets is visible to all; otherwise the student must match
    the targeted students, class, and/or section."""
    tstu = exam.get("target_students") or []
    tc = exam.get("target_classes") or []
    ts = exam.get("target_sections") or []
    if not tstu and not tc and not ts:
        return True
    uid = (user or {}).get("id", "")
    if tstu:  # individually-assigned (e.g. adaptive) — student match is sufficient
        return uid in tstu
    klass = (user or {}).get("klass", "")
    section = (user or {}).get("section", "")
    if tc and klass not in tc:
        return False
    if ts and section not in ts:
        return False
    return True


def list_exams(user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    ensure_seed()
    uid = (user or {}).get("id")
    attempted: Dict[str, str] = {}
    if uid:
        for a in _load("attempts", []):
            if a["student_id"] == uid:
                attempted[a["exam_id"]] = a["id"]  # latest wins
    out = []
    for e in _load("exams", []):
        if e.get("status") != "hosted":
            continue
        if not _exam_targets_user(e, user):
            continue
        out.append({
            "id": e["id"], "title": e["title"], "exam_type": e.get("exam_type", ""),
            "duration_min": e.get("duration_min", 0),
            "total_questions": len(e.get("questions", [])),
            "max_marks": sum(q.get("marks", 1) for q in e.get("questions", [])),
            "conducted_on": e.get("conducted_on", ""),
            "start_at": e.get("start_at"), "end_at": e.get("end_at"),
            "phase": exam_phase(e), "allow_retake": bool(e.get("allow_retake")),
            "target_classes": e.get("target_classes", []), "target_sections": e.get("target_sections", []),
            "adaptive": bool(e.get("adaptive")),
            "attempted": e["id"] in attempted, "attempt_id": attempted.get(e["id"]),
        })
    return out


def get_exam_full(exam_id: str) -> Optional[Dict[str, Any]]:
    ensure_seed()
    for e in _load("exams", []):
        if e["id"] == exam_id:
            return e
    return None


def get_exam_public(exam_id: str) -> Optional[Dict[str, Any]]:
    e = get_exam_full(exam_id)
    if not e:
        return None
    pub = _strip_answers(e)
    pub["phase"] = exam_phase(e)
    return pub


# ---------------------------------------------------------------------------
# Grading + attempts
# ---------------------------------------------------------------------------
def grade(exam: Dict[str, Any], answers: Dict[str, Any]) -> Dict[str, Any]:
    marking = exam.get("marking", {"correct": 4, "wrong": -1, "unattempted": 0})
    questions = exam.get("questions", [])
    per_subject: Dict[str, Dict[str, Any]] = {}
    per_question: List[Dict[str, Any]] = []
    total = 0
    correct = incorrect = unattempted = 0
    mcq_total = written_total = written_answered = 0

    def bucket(d: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
        return d.setdefault(key or "—", {"correct": 0, "incorrect": 0, "unattempted": 0, "marks": 0})

    for q in questions:
        qid = q["id"]
        if q.get("type") == "written":
            resp = answers.get(qid)
            resp = "" if resp is None else str(resp)
            written_total += 1
            if resp.strip():
                written_answered += 1
            per_question.append({"id": qid, "type": "written", "response": resp, "is_correct": None, "marks": 0})
            continue

        # MCQ — auto-graded
        mcq_total += 1
        marks_correct = q.get("marks", marking.get("correct", 4))
        chosen = answers.get(qid, None)
        chosen = int(chosen) if chosen is not None and str(chosen) != "" else None
        ci = q.get("correct_index")
        sub = bucket(per_subject, q.get("subject", ""))
        if chosen is None:
            unattempted += 1; sub["unattempted"] += 1
            mk = marking.get("unattempted", 0); is_correct = None
        elif chosen == ci:
            correct += 1; sub["correct"] += 1
            mk = marks_correct; is_correct = True
        else:
            incorrect += 1; sub["incorrect"] += 1
            mk = marking.get("wrong", 0); is_correct = False
        total += mk
        sub["marks"] += mk
        per_question.append({"id": qid, "type": "mcq", "chosen": chosen, "correct_index": ci, "is_correct": is_correct, "marks": mk})

    max_marks = sum(q.get("marks", marking.get("correct", 4)) for q in questions if q.get("type") != "written")
    attempted = correct + incorrect
    for v in per_subject.values():
        att = v["correct"] + v["incorrect"]
        v["accuracy"] = round(100 * v["correct"] / att, 1) if att else 0.0
    return {
        "score": total,
        "max_marks": max_marks,
        "percentage": round(100 * total / max_marks, 1) if max_marks else 0.0,
        "counts": {"total": len(questions), "mcq": mcq_total, "attempted": attempted, "correct": correct,
                   "incorrect": incorrect, "unattempted": unattempted,
                   "written": written_total, "written_answered": written_answered},
        "accuracy": round(100 * correct / attempted, 1) if attempted else 0.0,
        "per_subject": per_subject,
        "per_question": per_question,
    }


def record_attempt(user: Dict[str, Any], exam_id: str, answers: Dict[str, Any], time_spent_sec: int = 0) -> Optional[Dict[str, Any]]:
    exam = get_exam_full(exam_id)
    if not exam:
        return None
    phase = exam_phase(exam)
    if phase != "live":
        msg = {"upcoming": "This test hasn't started yet.", "ended": "This test has closed.",
               "draft": "This test is not available."}.get(phase, "This test is not open.")
        raise ValueError(msg)
    if not _exam_targets_user(exam, user):
        raise ValueError("This test isn't assigned to your class.")
    if not exam.get("allow_retake"):
        for a in _load("attempts", []):
            if a["exam_id"] == exam_id and a["student_id"] == user["id"]:
                raise ValueError("You have already attempted this test.")
    result = grade(exam, answers or {})
    with _LOCK:
        attempts = _load("attempts", [])
        attempt = {
            "id": "a_" + uuid.uuid4().hex[:12],
            "exam_id": exam_id,
            "exam_title": exam["title"],
            "exam_type": exam.get("exam_type", ""),
            "student_id": user["id"],
            "student_name": user.get("name", ""),
            "answers": {str(k): v for k, v in (answers or {}).items()},
            "time_spent_sec": int(time_spent_sec or 0),
            "submitted_at": int(time.time()),
            "result": result,
        }
        attempts.append(attempt)
        _save("attempts", attempts)
    return attempt


def list_attempts(uid: str) -> List[Dict[str, Any]]:
    out = [a for a in _load("attempts", []) if a["student_id"] == uid]
    out.sort(key=lambda a: a["submitted_at"], reverse=True)
    # trim the heavy per_question detail for list view
    summary = []
    for a in out:
        r = a["result"]
        summary.append({
            "id": a["id"], "exam_id": a["exam_id"], "exam_title": a["exam_title"],
            "exam_type": a["exam_type"], "submitted_at": a["submitted_at"],
            "score": r["score"], "max_marks": r["max_marks"], "percentage": r["percentage"],
            "accuracy": r["accuracy"], "counts": r["counts"],
        })
    return summary


def get_attempt(aid: str, uid: str) -> Optional[Dict[str, Any]]:
    for a in _load("attempts", []):
        if a["id"] == aid and a["student_id"] == uid:
            # attach the exam (with correct answers + stems) for review
            exam = get_exam_full(a["exam_id"])
            review = dict(a)
            review["exam"] = _strip_answers(exam) if exam else None
            # reveal solutions in review (post-submission only)
            if exam:
                review["answer_key"] = {q["id"]: q.get("correct_index") for q in exam.get("questions", [])}
                review["model_answers"] = {q["id"]: q.get("answer", "") for q in exam.get("questions", []) if q.get("type") == "written"}
            return review
    return None


def analytics(uid: str) -> Dict[str, Any]:
    attempts = [a for a in _load("attempts", []) if a["student_id"] == uid]
    attempts.sort(key=lambda a: a["submitted_at"])
    if not attempts:
        return {"exams_taken": 0, "avg_percentage": 0.0, "best_percentage": 0.0,
                "per_subject": {}, "trend": []}
    pcts = [a["result"]["percentage"] for a in attempts]
    subj: Dict[str, Dict[str, Any]] = {}
    for a in attempts:
        for s, v in a["result"].get("per_subject", {}).items():
            b = subj.setdefault(s, {"correct": 0, "incorrect": 0, "unattempted": 0})
            b["correct"] += v["correct"]; b["incorrect"] += v["incorrect"]; b["unattempted"] += v["unattempted"]
    for v in subj.values():
        att = v["correct"] + v["incorrect"]
        v["accuracy"] = round(100 * v["correct"] / att, 1) if att else 0.0
    return {
        "exams_taken": len(attempts),
        "avg_percentage": round(sum(pcts) / len(pcts), 1),
        "best_percentage": round(max(pcts), 1),
        "per_subject": subj,
        "trend": [{"exam_title": a["exam_title"], "submitted_at": a["submitted_at"],
                   "percentage": a["result"]["percentage"]} for a in attempts],
    }


# ---------------------------------------------------------------------------
# Exam authoring (teacher)
# ---------------------------------------------------------------------------
def create_exam(teacher: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Exam title is required")
    marking_in = data.get("marking") or {}
    marking = {
        "correct": int(marking_in.get("correct", 4)),
        "wrong": int(marking_in.get("wrong", -1)),
        "unattempted": int(marking_in.get("unattempted", 0)),
    }
    qs_in = data.get("questions") or []
    if not qs_in:
        raise ValueError("Add at least one question")
    questions = []
    for i, q in enumerate(qs_in, 1):
        stem = (q.get("stem") or "").strip()
        if not stem:
            raise ValueError(f"Question {i}: question text is required")
        qtype = "written" if (q.get("type") == "written") else "mcq"
        base = {
            "id": f"q{i}",
            "type": qtype,
            "stem": stem,
            "subject": (q.get("subject") or "").strip(),
            "chapter": (q.get("chapter") or "").strip(),
            "marks": int(q.get("marks") or marking["correct"]),
            "source_uid": q.get("source_uid") or None,
        }
        if qtype == "written":
            # No options; the extracted answer is the model answer (optional).
            base["answer"] = (q.get("answer") or "").strip()
        else:
            opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip() != ""]
            if len(opts) < 2:
                raise ValueError(f"Question {i}: provide at least 2 options (or mark it 'Written answer')")
            ci = q.get("correct_index")
            ci = int(ci) if ci is not None and str(ci) != "" else None
            if ci is None or ci < 0 or ci >= len(opts):
                raise ValueError(f"Question {i}: mark the correct option")
            base["options"] = opts
            base["correct_index"] = ci
        questions.append(base)
    def _epoch(v):
        try:
            return int(v) if v else None
        except (TypeError, ValueError):
            return None

    with _LOCK:
        ensure_seed()
        exams = _load("exams", [])
        exam = {
            "id": "exam_" + uuid.uuid4().hex[:10],
            "title": title,
            "exam_type": (data.get("exam_type") or "Custom").strip(),
            "status": "draft",
            "duration_min": int(data.get("duration_min") or 30),
            "conducted_on": (data.get("conducted_on") or "").strip(),
            "start_at": _epoch(data.get("start_at")),
            "end_at": _epoch(data.get("end_at")),
            "allow_retake": bool(data.get("allow_retake")),
            "target_classes": [str(c).strip() for c in (data.get("target_classes") or []) if str(c).strip()],
            "target_sections": [str(s).strip() for s in (data.get("target_sections") or []) if str(s).strip()],
            "target_students": [str(s).strip() for s in (data.get("target_students") or []) if str(s).strip()],
            "adaptive": bool(data.get("adaptive")),
            "marking": marking,
            "created_by": teacher["id"],
            "created_by_name": teacher.get("name", ""),
            "created_at": int(time.time()),
            "questions": questions,
        }
        exams.append(exam)
        _save("exams", exams)
        return exam


def list_my_exams(uid: str) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for a in _load("attempts", []):
        counts[a["exam_id"]] = counts.get(a["exam_id"], 0) + 1
    out = [e for e in _load("exams", []) if e.get("created_by") == uid]
    out.sort(key=lambda e: e.get("created_at", 0), reverse=True)
    return [{
        "id": e["id"], "title": e["title"], "exam_type": e.get("exam_type", ""),
        "status": e.get("status", "draft"), "total_questions": len(e.get("questions", [])),
        "max_marks": sum(q.get("marks", 1) for q in e.get("questions", [])),
        "duration_min": e.get("duration_min", 0), "created_at": e.get("created_at", 0),
        "start_at": e.get("start_at"), "end_at": e.get("end_at"), "phase": exam_phase(e),
        "target_classes": e.get("target_classes", []), "target_sections": e.get("target_sections", []),
        "target_students": e.get("target_students", []), "adaptive": bool(e.get("adaptive")),
        "attempt_count": counts.get(e["id"], 0),
    } for e in out]


def overall_report(uid: str, exam_type: str = "", klass: str = "") -> Dict[str, Any]:
    """Aggregate report across all the teacher's exams (Overall Report tab)."""
    exams = [e for e in _load("exams", []) if e.get("created_by") == uid]
    if exam_type:
        exams = [e for e in exams if e.get("exam_type") == exam_type]
    if klass:
        exams = [e for e in exams if klass in (e.get("target_classes") or []) or not (e.get("target_classes"))]
    exam_ids = {e["id"] for e in exams}
    attempts = [a for a in _load("attempts", []) if a["exam_id"] in exam_ids]

    by_exam: Dict[str, List[Dict[str, Any]]] = {}
    for a in attempts:
        by_exam.setdefault(a["exam_id"], []).append(a)

    rows, all_scores, students = [], [], set()
    for e in exams:
        ats = by_exam.get(e["id"], [])
        scores = [a["result"]["score"] for a in ats]
        for a in ats:
            students.add(a["student_id"]); all_scores.append(a["result"]["score"])
        rows.append({
            "exam": e["title"], "exam_type": e.get("exam_type", ""),
            "klass": ", ".join(e.get("target_classes") or []) or "All",
            "total_students": len({a["student_id"] for a in ats}),
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "max_score": max(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
        })
    rows.sort(key=lambda r: r["exam"].lower())
    return {
        "total_exams": len(exams),
        "avg_score": round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0,
        "best_score": max(all_scores) if all_scores else 0,
        "total_students": len(students),
        "rows": rows,
        "exam_types": sorted({e.get("exam_type", "") for e in _load("exams", []) if e.get("created_by") == uid and e.get("exam_type")}),
    }


def exam_report(uid: str, exam_id: str) -> Optional[Dict[str, Any]]:
    """Class-wide analytics for one of the teacher's exams."""
    exam = get_exam_full(exam_id)
    if not exam:
        return None
    if exam.get("created_by") != uid:
        raise PermissionError("You can only view reports for your own exams")
    attempts = [a for a in _load("attempts", []) if a["exam_id"] == exam_id]
    n = len(attempts)
    report: Dict[str, Any] = {
        "exam_id": exam_id, "title": exam["title"], "exam_type": exam.get("exam_type", ""),
        "status": exam.get("status", "draft"),
        "max_marks": sum(q.get("marks", 1) for q in exam.get("questions", [])),
        "participants": n,
    }
    if n == 0:
        report.update({"avg_percentage": 0, "high_percentage": 0, "low_percentage": 0,
                       "avg_score": 0, "avg_time_sec": 0, "distribution": [],
                       "per_question": [], "per_subject": {}, "leaderboard": []})
        return report

    pcts = [a["result"]["percentage"] for a in attempts]
    report["avg_percentage"] = round(sum(pcts) / n, 1)
    report["high_percentage"] = round(max(pcts), 1)
    report["low_percentage"] = round(min(pcts), 1)
    report["avg_score"] = round(sum(a["result"]["score"] for a in attempts) / n, 1)
    report["avg_time_sec"] = int(sum(a.get("time_spent_sec", 0) for a in attempts) / n)

    # score distribution (5 buckets of 20%)
    buckets = [0] * 5
    for p in pcts:
        buckets[min(4, int(p // 20))] += 1
    report["distribution"] = [{"range": f"{i*20}-{i*20+20}", "count": buckets[i]} for i in range(5)]

    # per-question analysis (correct rate over participants = difficulty index)
    agg: Dict[str, Dict[str, int]] = {}
    for a in attempts:
        for pq in a["result"].get("per_question", []):
            g = agg.setdefault(pq["id"], {"answered": 0, "correct": 0})
            if pq["chosen"] is not None:
                g["answered"] += 1
            if pq["is_correct"]:
                g["correct"] += 1
    report["per_question"] = [{
        "id": q["id"], "stem": q["stem"], "subject": q.get("subject", ""), "difficulty": q.get("difficulty", ""),
        "correct": agg.get(q["id"], {}).get("correct", 0),
        "answered": agg.get(q["id"], {}).get("answered", 0),
        "correct_rate": round(100 * agg.get(q["id"], {}).get("correct", 0) / n, 1),
    } for q in exam.get("questions", [])]

    # subject-wise class accuracy
    subj: Dict[str, Dict[str, Any]] = {}
    for a in attempts:
        for s, v in a["result"].get("per_subject", {}).items():
            b = subj.setdefault(s, {"correct": 0, "incorrect": 0, "unattempted": 0})
            b["correct"] += v["correct"]; b["incorrect"] += v["incorrect"]; b["unattempted"] += v["unattempted"]
    for v in subj.values():
        att = v["correct"] + v["incorrect"]
        v["accuracy"] = round(100 * v["correct"] / att, 1) if att else 0.0
    report["per_subject"] = subj

    # leaderboard — best attempt per student
    best: Dict[str, Dict[str, Any]] = {}
    for a in attempts:
        sid = a["student_id"]
        if sid not in best or a["result"]["score"] > best[sid]["result"]["score"]:
            best[sid] = a
    lb = sorted(best.values(), key=lambda a: a["result"]["score"], reverse=True)[:20]
    report["leaderboard"] = [{
        "student_name": a.get("student_name", "") or "Student",
        "score": a["result"]["score"], "max_marks": a["result"]["max_marks"],
        "percentage": a["result"]["percentage"], "accuracy": a["result"]["accuracy"],
    } for a in lb]

    # every submission (for monitoring who attempted, when)
    report["submissions"] = [{
        "student_name": a.get("student_name", "") or "Student",
        "score": a["result"]["score"], "max_marks": a["result"]["max_marks"],
        "percentage": a["result"]["percentage"],
        "submitted_at": a["submitted_at"], "time_spent_sec": a.get("time_spent_sec", 0),
    } for a in sorted(attempts, key=lambda a: a["submitted_at"], reverse=True)]
    return report


def set_exam_status(uid: str, exam_id: str, status: str) -> Optional[Dict[str, Any]]:
    status = "hosted" if status == "hosted" else "draft"
    with _LOCK:
        exams = _load("exams", [])
        found = None
        for e in exams:
            if e["id"] == exam_id:
                if e.get("created_by") != uid:
                    raise PermissionError("You can only change your own exams")
                e["status"] = status
                found = e
        if not found:
            return None
        _save("exams", exams)
        return {"id": found["id"], "status": found["status"]}


# ---------------------------------------------------------------------------
# Adaptive exams (per-student, performance-driven)
# ---------------------------------------------------------------------------
_DIFF_ORDER = {"Easy": 0, "Moderate": 1, "Difficult": 2}


def list_students() -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for a in _load("attempts", []):
        counts[a["student_id"]] = counts.get(a["student_id"], 0) + 1
    out = []
    for u in _load("users", []):
        if u.get("role") == "student":
            out.append({"id": u["id"], "name": u.get("name", ""), "username": u["username"],
                        "klass": u.get("klass", ""), "section": u.get("section", ""),
                        "attempts": counts.get(u["id"], 0)})
    out.sort(key=lambda x: (-x["attempts"], x["name"]))
    return out


def student_profile(uid: str) -> Dict[str, Any]:
    """Per-subject accuracy + overall + weak/strong subjects from MCQ history."""
    attempts = [a for a in _load("attempts", []) if a["student_id"] == uid]
    agg: Dict[str, Dict[str, int]] = {}
    c = i = 0
    for a in attempts:
        for s, v in a["result"].get("per_subject", {}).items():
            b = agg.setdefault(s, {"correct": 0, "incorrect": 0})
            b["correct"] += v["correct"]; b["incorrect"] += v["incorrect"]
            c += v["correct"]; i += v["incorrect"]
    per_subject = {}
    for s, b in agg.items():
        att = b["correct"] + b["incorrect"]
        per_subject[s] = {"correct": b["correct"], "incorrect": b["incorrect"],
                          "accuracy": round(100 * b["correct"] / att, 1) if att else 0.0}
    overall = round(100 * c / (c + i), 1) if (c + i) else 0.0
    by_acc = sorted(per_subject.items(), key=lambda kv: kv[1]["accuracy"])
    weak = [s for s, v in by_acc if v["accuracy"] < 60][:3] or [s for s, _ in by_acc[:2]]
    strong = [s for s, v in sorted(per_subject.items(), key=lambda kv: -kv[1]["accuracy"]) if v["accuracy"] >= 60][:3]
    return {"attempts": len(attempts), "overall_accuracy": overall,
            "per_subject": per_subject, "weak_subjects": weak, "strong_subjects": strong}


def cohort_profile(klass: str, section: str = "") -> Dict[str, Any]:
    """Aggregate performance for all students in a class (and section, if given)."""
    sids = {u["id"] for u in _load("users", [])
            if u.get("role") == "student" and u.get("klass", "") == klass and (not section or u.get("section", "") == section)}
    attempts = [a for a in _load("attempts", []) if a["student_id"] in sids]
    agg: Dict[str, Dict[str, int]] = {}
    c = i = 0
    for a in attempts:
        for s, v in a["result"].get("per_subject", {}).items():
            b = agg.setdefault(s, {"correct": 0, "incorrect": 0})
            b["correct"] += v["correct"]; b["incorrect"] += v["incorrect"]
            c += v["correct"]; i += v["incorrect"]
    per_subject = {}
    for s, b in agg.items():
        att = b["correct"] + b["incorrect"]
        per_subject[s] = {"correct": b["correct"], "incorrect": b["incorrect"],
                          "accuracy": round(100 * b["correct"] / att, 1) if att else 0.0}
    overall = round(100 * c / (c + i), 1) if (c + i) else 0.0
    by_acc = sorted(per_subject.items(), key=lambda kv: kv[1]["accuracy"])
    weak = [s for s, v in by_acc if v["accuracy"] < 60][:4] or [s for s, _ in by_acc[:2]]
    strong = [s for s, v in sorted(per_subject.items(), key=lambda kv: -kv[1]["accuracy"]) if v["accuracy"] >= 60][:4]
    return {"attempts": len(attempts), "students": len(sids), "overall_accuracy": overall,
            "per_subject": per_subject, "weak_subjects": weak, "strong_subjects": strong}


def adaptive_plan(profile: Dict[str, Any], mode: str = "weak", total: int = 15) -> Dict[str, Any]:
    per = profile.get("per_subject", {})
    overall = profile.get("overall_accuracy", 0.0)
    if mode == "strong":
        level = "Difficult" if overall >= 70 else "Moderate"
    else:  # remediation — ease difficulty to rebuild confidence
        level = "Easy" if overall < 45 else ("Moderate" if overall < 75 else "Difficult")

    subjects = list(profile.get("strong_subjects" if mode == "strong" else "weak_subjects", []))
    if not subjects:
        subjects = list(per.keys()) or ["Physics", "Chemistry", "Mathematics"]

    if mode == "strong":
        weights = {s: max(1.0, per.get(s, {}).get("accuracy", 50.0)) for s in subjects}
    else:
        weights = {s: max(1.0, 100.0 - per.get(s, {}).get("accuracy", 50.0)) for s in subjects}
    tw = sum(weights.values()) or 1.0

    alloc, assigned = [], 0
    for s in subjects:
        cnt = round(total * weights[s] / tw)
        alloc.append({"subject": s, "count": cnt}); assigned += cnt
    if alloc:
        alloc[0]["count"] = max(0, alloc[0]["count"] + (total - assigned))
    return {"target_level": level, "subjects": alloc}


def generate_adaptive(teacher: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    # "Strength Wise" -> strong; "Error Test"/"Previous Paper" -> weak (remediation)
    mode = "strong" if data.get("mode") in ("strong", "strength") else "weak"
    total = max(1, min(60, int(data.get("total") or 15)))
    sid = data.get("student_id")
    if sid:
        student = get_user(sid)
        if not student or student.get("role") != "student":
            raise ValueError("Pick a valid student.")
        profile = student_profile(student["id"])
        klass = student.get("klass", "")
        target = {"target_students": [student["id"]], "for": student.get("name", "student")}
    else:
        klass = str(data.get("klass") or "").strip()
        section = str(data.get("section") or "").strip()
        if not klass:
            raise ValueError("Select a class for the adaptive exam.")
        profile = cohort_profile(klass, section)
        target = {"target_classes": [klass], "target_sections": [section] if section else [], "for": f"Class {klass}" + (f"/{section}" if section else "")}

    plan = adaptive_plan(profile, mode, total)
    # Error Range (%) optionally narrows weak subjects to those whose error-rate is in band.
    ef, et = data.get("error_from"), data.get("error_to")
    if mode == "weak" and (ef not in (None, "") or et not in (None, "")):
        lo = float(ef) if ef not in (None, "") else 0.0
        hi = float(et) if et not in (None, "") else 100.0
        keep = [sl for sl in plan["subjects"]
                if lo <= (100.0 - profile.get("per_subject", {}).get(sl["subject"], {}).get("accuracy", 50.0)) <= hi]
        if keep:
            plan["subjects"] = keep

    from edu_pipeline.storage import database as bank_read
    tgt = _DIFF_ORDER.get(plan["target_level"], 1)
    questions, qn = [], 0
    for slot in plan["subjects"]:
        if slot["count"] <= 0:
            continue
        try:
            res = bank_read.search_items({"subject": [slot["subject"]], "class": [klass] if klass else [], "pageSize": 100})
            pool = res.get("items", [])
        except Exception:
            pool = []
        # prefer questions whose estimated difficulty is closest to the target level
        pool.sort(key=lambda it: abs(_DIFF_ORDER.get(it.get("difficulty", "Moderate"), 1) - tgt))
        for it in pool[:slot["count"]]:
            qn += 1
            ans = ""
            try:
                d = bank_read.get_item(it["id"])
                ans = ((d or {}).get("item") or {}).get("answer", "")
            except Exception:
                ans = ""
            questions.append({
                "id": f"q{qn}", "type": "written", "stem": it.get("stem", ""), "answer": ans,
                "subject": it.get("subject", slot["subject"]), "chapter": it.get("chapter_name", ""),
                "difficulty": it.get("difficulty", "Moderate"), "marks": 4, "source_uid": it.get("uid"),
            })
    return {"target": target, "profile": profile, "plan": plan, "mode": mode, "klass": klass, "questions": questions}


# ---------------------------------------------------------------------------
# Seed (a teacher-keyed sample NEET exam + a demo teacher account)
# ---------------------------------------------------------------------------
def ensure_seed() -> None:
    with _LOCK:
        if _path("exams").is_file():
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        exam = {
            "id": "exam_sample_foundation",
            "title": "IIT Foundation — Sample Test",
            "exam_type": "IIT Foundation",
            "status": "hosted",
            "duration_min": 20,
            "conducted_on": "2026-06-16",
            "marking": {"correct": 4, "wrong": -1, "unattempted": 0},
            "questions": [
                {"id": "q1", "subject": "Physics", "chapter": "Units & Measurements", "difficulty": "Easy", "type": "MCQ", "marks": 4,
                 "stem": "The SI unit of electric current is:", "options": ["Volt", "Ampere", "Ohm", "Watt"], "correct_index": 1},
                {"id": "q2", "subject": "Physics", "chapter": "Motion", "difficulty": "Moderate", "type": "MCQ", "marks": 4,
                 "stem": "A body of mass 2 kg accelerates at 3 m/s². The net force on it is:", "options": ["1.5 N", "5 N", "6 N", "9 N"], "correct_index": 2},
                {"id": "q3", "subject": "Physics", "chapter": "Work & Energy", "difficulty": "Difficult", "type": "MCQ", "marks": 4,
                 "stem": "The work done by a centripetal force in uniform circular motion is:", "options": ["Maximum", "Zero", "Negative", "Equal to KE"], "correct_index": 1},
                {"id": "q4", "subject": "Chemistry", "chapter": "Atomic Structure", "difficulty": "Easy", "type": "MCQ", "marks": 4,
                 "stem": "The number of protons in a neutral oxygen atom is:", "options": ["6", "7", "8", "16"], "correct_index": 2},
                {"id": "q5", "subject": "Chemistry", "chapter": "Periodic Classification", "difficulty": "Moderate", "type": "MCQ", "marks": 4,
                 "stem": "Which element has the highest electronegativity?", "options": ["Oxygen", "Fluorine", "Chlorine", "Nitrogen"], "correct_index": 1},
                {"id": "q6", "subject": "Chemistry", "chapter": "Chemical Bonding", "difficulty": "Difficult", "type": "MCQ", "marks": 4,
                 "stem": "The hybridization of carbon in methane (CH₄) is:", "options": ["sp", "sp²", "sp³", "sp³d"], "correct_index": 2},
                {"id": "q7", "subject": "Mathematics", "chapter": "Number Systems", "difficulty": "Easy", "type": "MCQ", "marks": 4,
                 "stem": "The value of 3² + 4² is:", "options": ["12", "25", "7", "49"], "correct_index": 1},
                {"id": "q8", "subject": "Mathematics", "chapter": "Linear Equations", "difficulty": "Moderate", "type": "MCQ", "marks": 4,
                 "stem": "If 2x + 3 = 11, then x equals:", "options": ["2", "4", "5", "8"], "correct_index": 1},
                {"id": "q9", "subject": "Mathematics", "chapter": "Mensuration", "difficulty": "Difficult", "type": "MCQ", "marks": 4,
                 "stem": "The area of a circle of radius 7 cm (π = 22/7) is:", "options": ["154 cm²", "44 cm²", "49 cm²", "22 cm²"], "correct_index": 0},
            ],
        }
        _save("exams", [exam])
        if not _path("users").is_file():
            _save("users", [])
        if not _path("attempts").is_file():
            _save("attempts", [])
