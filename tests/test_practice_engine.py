"""Practice Engine, question tagging and MCQ parsing (PRD Phase 1 MVP).

No MySQL: the bank is stubbed via ``practice._fetch_rows`` and session storage
is redirected to tmp_path, so these run in the default suite.
"""

from __future__ import annotations

import time

import pytest

from edu_pipeline.assessment import dashboard as dash
from edu_pipeline.assessment import practice
from edu_pipeline.generators.questions import mcq_parser, tagger


# ---------------------------------------------------------------------------
# Tagger
# ---------------------------------------------------------------------------
class TestCognitiveLevel:
    @pytest.mark.parametrize("question,expected", [
        ("Define inertia.", "Remember"),
        ("State the laws of reflection.", "Remember"),
        ("Explain why the sky appears blue.", "Understand"),
        ("Calculate the momentum of a 2 kg ball at 3 m/s.", "Apply"),
        ("Compare conductors and insulators.", "Analyse"),
        ("Justify the use of a fuse in a circuit.", "Evaluate"),
        ("Design an experiment to measure density.", "Create"),
    ])
    def test_maps_verbs_to_bloom_levels(self, question, expected):
        assert tagger.cognitive_level(question) == expected

    def test_highest_level_wins_when_several_match(self):
        # "explain" is Understand, "compare" is Analyse -> Analyse.
        assert tagger.cognitive_level("Compare and explain the two circuits.") == "Analyse"

    def test_question_type_acts_as_a_floor(self):
        # No recognisable verb, but a Numerical row is at least Apply.
        assert tagger.cognitive_level("The value of x in the circuit shown.", "Numerical") == "Apply"

    def test_type_floor_does_not_lower_a_higher_text_match(self):
        assert tagger.cognitive_level("Justify the answer.", "Fill in the Blanks") == "Evaluate"

    def test_bare_mcq_stem_is_recall(self):
        assert tagger.cognitive_level("Which of the following is a metal?", "MCQ") == "Remember"

    def test_causal_mcq_stem_is_comprehension(self):
        assert tagger.cognitive_level("Glass is transparent due to its structure.", "MCQ") == "Understand"

    def test_defaults_to_understand_when_nothing_matches(self):
        assert tagger.cognitive_level("The circuit shown above.", "") == "Understand"


class TestDifficulty:
    def test_short_recall_is_easy(self):
        assert tagger.estimate_difficulty("Define mass.", "Short Answer") == "Easy"

    def test_long_analytical_question_is_difficult(self):
        stem = "Compare and analyse " + ("the behaviour of the circuit under load " * 8)
        assert tagger.estimate_difficulty(stem, "HOTS") == "Difficult"

    def test_returns_a_known_band(self):
        assert tagger.estimate_difficulty("Calculate v when u=2.", "Numerical") in tagger.DIFFICULTIES

    def test_math_markup_raises_difficulty(self):
        plain = tagger.estimate_difficulty("Find the value of the expression below.", "Numerical")
        mathy = tagger.estimate_difficulty(
            "Find the value of <math><mfrac><mi>a</mi><mi>b</mi></mfrac></math> below.", "Numerical")
        order = tagger.DIFFICULTIES
        assert order.index(mathy) >= order.index(plain)


class TestSubtopic:
    HEADINGS = ("Laws of Reflection", "Mirror Formula", "Refractive Index")

    def test_matches_the_overlapping_heading(self):
        assert tagger.subtopic("State the laws of reflection.", self.HEADINGS) == "Laws of Reflection"

    def test_returns_empty_when_nothing_overlaps(self):
        assert tagger.subtopic("What is photosynthesis?", self.HEADINGS) == ""

    def test_single_word_overlap_is_rejected_as_coincidence(self):
        # "formula" alone should not attach the two-word "Mirror Formula".
        assert tagger.subtopic("Write any formula you know.", ("Mirror Formula",)) == ""

    def test_no_headings_yields_empty(self):
        assert tagger.subtopic("State the laws of reflection.", ()) == ""


class TestTagQuestion:
    def test_returns_all_four_attributes(self):
        tags = tagger.tag_question("Define inertia.", "Short Answer", "Motion")
        assert set(tags) == {"difficulty", "subtopic", "cognitive_level", "learning_objective"}

    def test_objective_is_phrased_for_the_level(self):
        tags = tagger.tag_question("Calculate the force.", "Numerical", "Motion")
        assert tags["cognitive_level"] == "Apply"
        assert "Apply" in tags["learning_objective"]

    def test_objective_falls_back_to_chapter_when_no_subtopic(self):
        tags = tagger.tag_question("Define inertia.", "Short Answer", "Laws of Motion")
        assert "Laws of Motion" in tags["learning_objective"]

    def test_tag_items_echoes_row_id(self):
        out = tagger.tag_items([{"id": 7, "question": "Define x.", "question_type": "Short Answer"}])
        assert out[0]["id"] == 7

    def test_subtopic_is_truncated_to_column_width(self):
        long_heading = "A" * 400
        tags = tagger.tag_question("A" * 400, "Short Answer", "", (long_heading,))
        assert len(tags["subtopic"]) <= 255


# ---------------------------------------------------------------------------
# MCQ parser
# ---------------------------------------------------------------------------
class TestParseOptions:
    def test_splits_an_inline_option_list(self):
        stem, opts = mcq_parser.parse_options(
            "Which is a metal? (a) oxygen (b) iron (c) sulphur (d) neon")
        assert stem == "Which is a metal?"
        assert opts == ["oxygen", "iron", "sulphur", "neon"]

    def test_handles_numeric_markers(self):
        _stem, opts = mcq_parser.parse_options("Pick one. 1) alpha 2) beta 3) gamma")
        assert opts == ["alpha", "beta", "gamma"]

    def test_returns_no_options_for_prose(self):
        stem, opts = mcq_parser.parse_options("Explain the process of osmosis in detail.")
        assert opts == [] and stem.startswith("Explain")

    def test_caps_at_four_options(self):
        _stem, opts = mcq_parser.parse_options("Q (a) 1 (b) 2 (c) 3 (d) 4")
        assert len(opts) <= mcq_parser.MAX_OPTIONS


class TestParseCorrectIndex:
    OPTS = ["oxygen", "iron", "sulphur", "neon"]

    @pytest.mark.parametrize("answer,expected", [
        ("(b) iron", 1), ("b) iron", 1), ("Ans: c", 2), ("Answer - D", 3), ("(a)", 0),
    ])
    def test_reads_the_key_letter(self, answer, expected):
        assert mcq_parser.parse_correct_index(answer, self.OPTS) == expected

    def test_falls_back_to_exact_text_match(self):
        assert mcq_parser.parse_correct_index("iron", self.OPTS) == 1

    def test_rejects_an_unrecoverable_key(self):
        assert mcq_parser.parse_correct_index("It is a shiny metal used widely.", self.OPTS) is None

    def test_rejects_a_letter_beyond_the_option_list(self):
        assert mcq_parser.parse_correct_index("(d) neon", ["oxygen", "iron"]) is None

    def test_empty_answer_is_rejected(self):
        assert mcq_parser.parse_correct_index("", self.OPTS) is None


class TestToMcq:
    def test_builds_a_gradable_question(self):
        row = {"id": 3, "question": "Which is a metal? (a) oxygen (b) iron (c) neon",
               "answer": "(b) iron", "question_type": "MCQ", "difficulty": "Easy",
               "chapter_id": 1, "chapter_name": "Metals"}
        m = mcq_parser.to_mcq(row)
        assert m["correct_index"] == 1 and m["source_id"] == 3
        assert m["options"][m["correct_index"]] == "iron"

    def test_rejects_rows_without_options(self):
        assert mcq_parser.to_mcq({"question": "Explain osmosis.", "answer": "It is diffusion."}) is None

    def test_rejects_rows_whose_key_cannot_be_established(self):
        # This is the misaligned-answer case seen in the live bank: the answer
        # column holds the *next* question rather than a key.
        row = {"question": "Which is a metal? (a) oxygen (b) iron",
               "answer": "When glass is heated, it (a) melts (b) vapourises"}
        assert mcq_parser.to_mcq(row) is None

    def test_to_mcqs_drops_only_the_unusable(self):
        rows = [
            {"question": "Q1 (a) x (b) y", "answer": "(a) x"},
            {"question": "Explain something.", "answer": "Because."},
        ]
        assert len(mcq_parser.to_mcqs(rows)) == 1


# ---------------------------------------------------------------------------
# Practice engine
# ---------------------------------------------------------------------------
def make_row(i, difficulty="Moderate", chapter_id=1, subtopic="Optics"):
    return {
        "id": i, "chapter_id": chapter_id, "chapter_name": "Light", "book_slug": "BOOK",
        "question": f"Question {i}? (a) alpha (b) beta (c) gamma (d) delta",
        "answer": "(b) beta", "question_type": "MCQ", "difficulty": difficulty,
        "subtopic": subtopic, "cognitive_level": "Understand",
        "learning_objective": "Explain the underlying principles of Optics.",
    }


@pytest.fixture
def bank(monkeypatch):
    """A 60-row stub bank with an even difficulty spread."""
    levels = ["Easy", "Moderate", "Difficult"]
    rows = [make_row(i, levels[i % 3]) for i in range(1, 61)]

    def fake_fetch(where="", params=(), cap=1200):
        out = rows
        if "id IN" in where:
            wanted = set(params)
            out = [r for r in rows if r["id"] in wanted]
        return out[:cap]

    monkeypatch.setattr(practice, "_fetch_rows", fake_fetch)
    return rows


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Redirect the JSON session store into tmp_path."""
    data = {}

    monkeypatch.setattr(practice, "_load", lambda name, default: data.get(name, default))
    monkeypatch.setattr(practice, "_save", lambda name, payload: data.__setitem__(name, payload))
    monkeypatch.setattr(dash, "_load", lambda name, default: data.get(name, default))
    monkeypatch.setattr(dash, "_save", lambda name, payload: data.__setitem__(name, payload))
    return data


USER = {"id": "u_test", "name": "Test Student", "role": "student"}


def answer_all(sid, pattern):
    """pattern(i, correct_index) -> chosen index or None."""
    s = practice.get_session(USER["id"], sid)
    for i, q in enumerate(s["questions"]):
        practice.answer(USER["id"], sid, i, pattern(i, q["correct_index"]), time_sec=10)


class TestModeSizes:
    @pytest.mark.parametrize("mode,expected", [
        ("topic", 12), ("chapter", 30), ("mixed", 20),
        ("sprint", 10), ("adaptive", 18), ("daily", 5),
    ])
    def test_default_sizes_match_the_prd(self, bank, store, mode, expected):
        kw = {"chapter_id": 1} if practice.MODES[mode]["needs"] == "chapter" else {}
        assert practice.start_session(USER, mode, **kw)["total"] == expected

    def test_daily_challenge_is_five_questions(self, bank, store):
        # Regression: "mixed" has a 10-question floor that used to clamp the
        # 5-question Daily Challenge up to 10.
        assert dash.start_daily_challenge(USER)["total"] == dash.DAILY_CHALLENGE_SIZE

    def test_total_is_clamped_to_the_mode_range(self, bank, store):
        assert practice.start_session(USER, "topic", chapter_id=1, total=999)["total"] == 15
        assert practice.start_session(USER, "topic", chapter_id=1, total=1)["total"] == 5

    def test_sprint_carries_a_time_limit(self, bank, store):
        assert practice.start_session(USER, "sprint")["time_limit_sec"] == 300

    def test_chapter_modes_require_a_chapter(self, bank, store):
        with pytest.raises(ValueError, match="needs a chapter"):
            practice.start_session(USER, "chapter")

    def test_unknown_mode_is_rejected(self, bank, store):
        with pytest.raises(ValueError, match="Unknown practice mode"):
            practice.start_session(USER, "nonsense")


class TestAnswerSecrecy:
    def test_client_view_hides_the_key_while_active(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1)
        assert all("correct_index" not in q for q in s["questions"])

    def test_key_is_revealed_once_revealed_is_requested(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1)
        full = practice.get_session(USER["id"], s["id"])
        pub = practice.public_session(full, reveal=True)
        assert all("correct_index" in q for q in pub["questions"])


class TestGradingAndReport:
    def test_counts_correct_incorrect_and_skipped(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci if i < 6 else (None if i >= 8 else (ci + 1) % 4))
        rep = practice.finish(USER["id"], s["id"])
        assert rep["counts"] == {"total": 10, "correct": 6, "incorrect": 2,
                                 "skipped": 2, "attempted": 8}

    def test_accuracy_uses_attempted_and_score_uses_total(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci if i < 6 else (None if i >= 8 else (ci + 1) % 4))
        rep = practice.finish(USER["id"], s["id"])
        assert rep["accuracy"] == 75.0    # 6 of 8 attempted
        assert rep["score_pct"] == 60.0   # 6 of 10 total

    def test_report_breaks_down_by_difficulty_and_bloom(self, bank, store):
        s = practice.start_session(USER, "chapter", chapter_id=1)
        answer_all(s["id"], lambda i, ci: ci)
        rep = practice.finish(USER["id"], s["id"])
        assert rep["per_difficulty"] and rep["per_cognitive_level"] and rep["per_topic"]
        assert all(b["accuracy"] == 100.0 for b in rep["per_difficulty"].values())

    def test_report_records_time_per_question(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=5)
        answer_all(s["id"], lambda i, ci: ci)
        rep = practice.finish(USER["id"], s["id"])
        assert rep["time_spent_sec"] == 50 and rep["avg_time_sec"] == 10.0

    def test_mistakes_include_skipped_questions(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=6)
        answer_all(s["id"], lambda i, ci: None if i >= 4 else ci)
        rep = practice.finish(USER["id"], s["id"])
        assert len(rep["mistakes"]) == 2
        assert all(m["skipped"] for m in rep["mistakes"])

    def test_answering_twice_is_rejected_after_finish(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=5)
        practice.finish(USER["id"], s["id"])
        with pytest.raises(ValueError, match="already finished"):
            practice.answer(USER["id"], s["id"], 0, 1)

    def test_out_of_range_index_is_rejected(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=5)
        with pytest.raises(ValueError, match="out of range"):
            practice.answer(USER["id"], s["id"], 99, 1)

    def test_another_user_cannot_read_the_session(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=5)
        assert practice.get_session("someone_else", s["id"]) is None


class TestMastery:
    @pytest.mark.parametrize("pct,band", [
        (95.0, "Mastered"), (75.0, "Proficient"), (55.0, "Developing"), (20.0, "Needs Work"),
    ])
    def test_bands(self, pct, band):
        assert practice.mastery(pct)["band"] == band

    def test_chapter_test_reports_mastery(self, bank, store):
        s = practice.start_session(USER, "chapter_test", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci)
        rep = practice.finish(USER["id"], s["id"])
        assert rep["mastery"]["band"] == "Mastered" and rep["mastery"]["passed"]

    def test_practice_modes_carry_no_mastery(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=5)
        answer_all(s["id"], lambda i, ci: ci)
        assert "mastery" not in practice.finish(USER["id"], s["id"])


class TestAdaptiveDifficulty:
    def test_raises_difficulty_on_a_hot_streak(self, bank, store):
        s = practice.start_session(USER, "adaptive", total=15)
        last = None
        for i in range(5):
            q = practice.get_session(USER["id"], s["id"])["questions"][i]
            last = practice.answer(USER["id"], s["id"], i, q["correct_index"])
        assert last["next_difficulty"] == "Difficult"

    def test_lowers_difficulty_on_a_cold_streak(self, bank, store):
        s = practice.start_session(USER, "adaptive", total=15)
        last = None
        for i in range(5):
            q = practice.get_session(USER["id"], s["id"])["questions"][i]
            last = practice.answer(USER["id"], s["id"], i, (q["correct_index"] + 1) % 4)
        assert last["next_difficulty"] == "Easy"


class TestHistoryAndMistakePractice:
    def test_finished_skips_enter_the_mistake_queue(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=6)
        answer_all(s["id"], lambda i, ci: None if i >= 4 else ci)
        practice.finish(USER["id"], s["id"])
        assert practice.history(USER["id"])["mistake_count"] == 2

    def test_abandoned_sessions_do_not_pollute_the_mistake_queue(self, bank, store):
        # Regression: untouched questions in an unfinished session were being
        # counted as skips, inflating the queue to the whole session.
        practice.start_session(USER, "chapter", chapter_id=1, total=30)
        assert practice.history(USER["id"])["mistake_count"] == 0

    def test_a_later_correct_answer_clears_the_mistake(self, bank, store):
        s1 = practice.start_session(USER, "topic", chapter_id=1, total=5)
        answer_all(s1["id"], lambda i, ci: (ci + 1) % 4)
        practice.finish(USER["id"], s1["id"])
        assert practice.history(USER["id"])["mistake_count"] == 5

        s2 = practice.start_session(USER, "mistake", total=5)
        answer_all(s2["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s2["id"])
        assert practice.history(USER["id"])["mistake_count"] == 0

    def test_mistake_practice_needs_prior_mistakes(self, bank, store):
        with pytest.raises(practice.PracticeUnavailable, match="No past mistakes"):
            practice.start_session(USER, "mistake")

    def test_history_tracks_per_chapter_accuracy(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci if i < 5 else (ci + 1) % 4)
        practice.finish(USER["id"], s["id"])
        assert practice.history(USER["id"])["per_chapter"][1]["accuracy"] == 50.0


class TestRecommendation:
    def test_strong_result_advances_to_a_chapter_test(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci)
        assert practice.finish(USER["id"], s["id"])["recommendation"]["action"] == "advance"

    def test_weak_result_sends_the_student_to_revision(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: (ci + 1) % 4)
        assert practice.finish(USER["id"], s["id"])["recommendation"]["action"] == "revise"

    def test_nothing_attempted_asks_for_a_retry(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=5)
        answer_all(s["id"], lambda i, ci: None)
        assert practice.finish(USER["id"], s["id"])["recommendation"]["action"] == "retry"


# ---------------------------------------------------------------------------
# Dashboard widgets
# ---------------------------------------------------------------------------
class TestDashboardWidgets:
    def test_all_six_prd_widgets_are_present(self, bank, store, monkeypatch):
        monkeypatch.setattr(dash, "_chapter_question_count", lambda cid: 100)
        widgets = dash.student_dashboard(USER)["widgets"]
        assert set(widgets) == {
            "daily_goal", "continue_learning", "daily_challenge",
            "ai_recommendation", "weekly_progress", "saved_content",
        }

    def test_daily_goal_tracks_todays_answers(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s["id"])
        g = dash.widget_daily_goal(USER["id"], practice.history(USER["id"]))
        assert g["done"] == 10 and g["goal"] == dash.DEFAULT_DAILY_GOAL and g["remaining"] == 10

    def test_daily_goal_is_configurable_and_clamped(self, bank, store):
        assert dash.set_daily_goal(USER["id"], 40)["daily_goal"] == 40
        assert dash.set_daily_goal(USER["id"], 99999)["daily_goal"] == 200
        assert dash.set_daily_goal(USER["id"], 1)["daily_goal"] == 5

    def test_continue_learning_hides_when_nothing_practised(self, bank, store):
        assert dash.widget_continue_learning(USER["id"], practice.history(USER["id"]))["show"] is False

    def test_continue_learning_shows_partial_progress(self, bank, store, monkeypatch):
        monkeypatch.setattr(dash, "_chapter_question_count", lambda cid: 100)
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s["id"])
        w = dash.widget_continue_learning(USER["id"], practice.history(USER["id"]))
        assert w["show"] is True and w["pct"] == 10

    def test_continue_learning_hides_once_chapter_is_complete(self, bank, store, monkeypatch):
        monkeypatch.setattr(dash, "_chapter_question_count", lambda cid: 10)
        s = practice.start_session(USER, "topic", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s["id"])
        assert dash.widget_continue_learning(USER["id"], practice.history(USER["id"]))["show"] is False

    def test_daily_challenge_resets_and_completes(self, bank, store):
        assert dash.widget_daily_challenge(USER["id"])["status"] == "available"
        s = dash.start_daily_challenge(USER)
        assert dash.widget_daily_challenge(USER["id"])["status"] == "in_progress"
        answer_all(s["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s["id"])
        state = dash.widget_daily_challenge(USER["id"])
        assert state["status"] == "completed" and state["score"] == 5

    def test_second_challenge_returns_the_same_session(self, bank, store):
        first = dash.start_daily_challenge(USER)
        assert dash.start_daily_challenge(USER)["id"] == first["id"]

    def test_completed_challenge_cannot_be_restarted(self, bank, store):
        s = dash.start_daily_challenge(USER)
        answer_all(s["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s["id"])
        with pytest.raises(ValueError, match="already complete"):
            dash.start_daily_challenge(USER)

    def test_recommendation_starts_a_new_student_on_chapter_practice(self, bank, store):
        w = dash.widget_ai_recommendation(USER["id"], practice.history(USER["id"]))
        assert w["action"] == "start" and w["why"]

    def test_recommendation_prioritises_a_large_mistake_queue(self, bank, store):
        s = practice.start_session(USER, "chapter", chapter_id=1, total=10)
        answer_all(s["id"], lambda i, ci: (ci + 1) % 4)
        practice.finish(USER["id"], s["id"])
        w = dash.widget_ai_recommendation(USER["id"], practice.history(USER["id"]))
        assert w["action"] == "mistake_practice"

    def test_weekly_progress_covers_seven_days(self, bank, store):
        w = dash.widget_weekly_progress(USER["id"])
        assert len(w["series"]) == 7 and w["ok"]

    def test_weekly_progress_counts_todays_activity(self, bank, store):
        s = practice.start_session(USER, "topic", chapter_id=1, total=8)
        answer_all(s["id"], lambda i, ci: ci)
        practice.finish(USER["id"], s["id"])
        w = dash.widget_weekly_progress(USER["id"])
        assert w["total_answered"] == 8 and w["active_days"] == 1
        assert w["series"][-1]["day"] == time.strftime("%Y-%m-%d")

    def test_saved_content_reports_unavailable_rather_than_faking_data(self, bank, store):
        # The Saved Library ships with the Learn Module; the widget must not
        # invent items in the meantime.
        w = dash.widget_saved_content(USER["id"])
        assert w["ok"] and w["available"] is False and w["items"] == []

    def test_a_failing_widget_degrades_alone(self, bank, store, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("bank down")

        monkeypatch.setattr(dash, "widget_weekly_progress", boom)
        widgets = dash.student_dashboard(USER)["widgets"]
        assert widgets["weekly_progress"]["ok"] is False
        assert widgets["daily_goal"]["ok"] is True
