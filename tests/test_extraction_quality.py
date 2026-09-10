"""Tests for the post-extraction quality checks.

These guard the guard: each check exists because a real book shipped with that
fault while the extraction reported success, so the tests are written as the
smallest document that reproduces the fault -- and, just as importantly, the
neighbouring document that must *not* trip it.
"""

from __future__ import annotations

from edu_pipeline.extraction import quality


def document(chapters):
    """A questions sidecar with the given (number, name, questions) chapters."""
    return {
        "class": "10",
        "subject": "Chemistry",
        "book_name": "Book",
        "chapters": [
            {"chapter_number": n, "chapter_name": name, "questions": questions}
            for n, name, questions in chapters
        ],
    }


def questions(count, *, answered=True, prefix="Question"):
    return [
        {"question_number": str(i),
         # Long enough to clear the duplicate check's minimum key length, which
         # exists so two short stems are not mistaken for the same question.
         "question": f"{prefix} number {i}: explain what happens to the sample "
                     f"when it is heated and describe the observation.",
         "answer": "yes" if answered else ""}
        for i in range(1, count + 1)
    ]


def clean_book():
    """Three comparable chapters, each with its own questions, all answered."""
    return document([(1, "One", questions(50, prefix="Alpha")),
                     (2, "Two", questions(50, prefix="Beta")),
                     (3, "Three", questions(50, prefix="Gamma"))])


def checks_named(findings, name):
    return [f for f in findings if f.check == name]


class TestChapterSize:
    def test_a_chapter_that_swallowed_its_neighbours_fails(self):
        """Chemistry chapter 3 held 13,465 lines against a 3,000-line median."""
        doc = document([(1, "One", questions(50)), (2, "Two", questions(50)),
                        (3, "Three", questions(600))])
        found = checks_named(quality.check_chapters_are_comparable(doc), "chapter_size")
        assert len(found) == 1
        assert "Chapter 3" in found[0].message

    def test_ordinary_variation_between_chapters_passes(self):
        doc = document([(1, "One", questions(40)), (2, "Two", questions(90)),
                        (3, "Three", questions(120))])
        assert quality.check_chapters_are_comparable(doc) == []


class TestDuplicateQuestions:
    def test_a_stale_split_duplicating_hundreds_fails(self):
        shared = questions(60, prefix="Shared")
        doc = document([(1, "One", shared), (2, "Two", list(shared)),
                        (3, "Three", questions(30))])
        found = checks_named(quality.check_chapters_are_distinct(doc), "duplicate_questions")
        assert found and found[0].severity == "fail"

    def test_a_book_reprinting_a_few_questions_only_warns(self):
        """IUPAC naming really does appear in two organic chapters."""
        repeated = questions(2, prefix="Repeated")
        doc = document([(1, "One", questions(200) + repeated),
                        (2, "Two", questions(200, prefix="Other") + list(repeated))])
        found = checks_named(quality.check_chapters_are_distinct(doc), "duplicate_questions")
        assert found and found[0].severity == "warn"

    def test_shared_mathml_markup_is_not_a_duplicate(self):
        """Two unrelated questions opening on an equation share their markup."""
        math = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mi>x</mi></mrow></math>'
        doc = document([
            (1, "One", [{"question_number": "1", "question": math, "answer": "a"}]),
            (2, "Two", [{"question_number": "1", "question": math, "answer": "b"}]),
        ])
        assert quality.check_chapters_are_distinct(doc) == []


class TestAnswerKeys:
    def test_a_chapter_that_lost_its_answer_key_fails(self):
        """The fullwidth SOLUTIONS bracket cost chapter 5 all 523 of its answers."""
        doc = document([(1, "One", questions(60)), (2, "Two", questions(60)),
                        (5, "Five", questions(60, answered=False))])
        found = checks_named(quality.check_answer_keys_were_found(doc), "answer_key")
        assert len(found) == 1
        assert "Chapter 5" in found[0].message

    def test_a_book_that_prints_no_answer_key_is_not_a_fault(self):
        """Chemistry chapters 6 and 9 genuinely have none."""
        doc = document([(1, "One", questions(60, answered=False)),
                        (2, "Two", questions(60, answered=False))])
        assert quality.check_answer_keys_were_found(doc) == []

    def test_a_short_chapter_is_not_judged(self):
        doc = document([(1, "One", questions(60)),
                        (2, "Two", questions(5, answered=False))])
        assert quality.check_answer_keys_were_found(doc) == []


class TestRunawayQuestions:
    def test_an_answer_that_ran_into_the_theory_fails(self):
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Draw the structure.",
             "answer": "x" * 9000},
        ])])
        found = checks_named(quality.check_no_runaway_questions(doc), "runaway_question")
        assert found and "9,0" in found[0].message.replace("9,00", "9,0")

    def test_a_long_question_made_of_figures_and_maths_passes(self):
        """A question carrying many structure diagrams is long for a good reason."""
        figures = "".join(f'<img class="imgSvg" src="data:image/svg+xml;base64,{"A" * 800}"/>'
                          for _ in range(20))
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Draw the structures.",
             "answer": figures},
        ])])
        assert quality.check_no_runaway_questions(doc) == []


class TestPageFurniture:
    def test_furniture_reaching_a_question_fails(self):
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Water gas is [JSTSE] hot", "answer": "a"},
        ])])
        found = checks_named(quality.check_no_page_furniture(doc), "page_furniture")
        assert found and "exam tag" in found[0].message

    def test_fullwidth_options_are_reported(self):
        """"（a）" never parses as an option, so the question silently loses them."""
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Which is correct？\n（a） yes", "answer": "a"},
        ])])
        found = checks_named(quality.check_no_page_furniture(doc), "page_furniture")
        assert found and "fullwidth" in found[0].message

    def test_a_clean_question_passes_every_check(self):
        doc = clean_book()
        assert quality.check_questions_document(doc) == []


class TestReport:
    def test_a_clean_book_reports_ok(self):
        report = quality.format_report(quality.check_questions_document(clean_book()), "Book")
        assert report.endswith("OK")

    def test_findings_name_the_check_and_the_evidence(self):
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Water gas is [NTSE] hot", "answer": "a"},
        ])])
        report = quality.format_report(quality.check_questions_document(doc), "Book")
        assert "[FAIL]" in report and "page_furniture" in report


class TestIntegrity:
    """Checks that catch output which is well-formed but wrong."""

    def test_an_answer_holding_a_question_fails(self):
        """The known alignment bug: the answer column picks up the next question."""
        stem = ("Explain what happens to the sample when it is heated and "
                "describe the observation carefully.")
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Define an acid in the Bronsted sense here.",
             "answer": stem},
            {"question_number": "2", "question": stem, "answer": "It melts."},
        ])])
        found = checks_named(quality.check_answers_are_answers(doc), "answer_is_a_question")
        assert found and found[0].severity == "fail"

    def test_an_ordinary_answer_passes(self):
        doc = clean_book()
        assert quality.check_answers_are_answers(doc) == []

    def test_a_key_naming_a_missing_option_fails(self):
        """Key "(d)" against three options means the option list lost one."""
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Pick one.",
             "options": {"a": "x", "b": "y", "c": "z"}, "answer": "(d)"},
        ])])
        found = checks_named(quality.check_answer_keys_match_options(doc),
                             "answer_outside_options")
        assert found and "(d)" in found[0].evidence[0]

    def test_a_key_naming_a_present_option_passes(self):
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Pick one.",
             "options": {"a": "x", "b": "y", "c": "z", "d": "w"}, "answer": "(d)"},
        ])])
        assert quality.check_answer_keys_match_options(doc) == []

    def test_a_written_answer_is_not_judged_against_options(self):
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Explain why.",
             "options": {"a": "x", "b": "y"}, "answer": "Because it expands on heating."},
        ])])
        assert quality.check_answer_keys_match_options(doc) == []

    def test_a_figure_token_with_no_figure_fails(self):
        """A passage's diagram was referenced but never attached to the question."""
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Study the figure.",
             "question_stem": "The circuit shown [image:img_068] carries a current.",
             "answer": "a", "images": []},
        ])])
        found = checks_named(quality.check_figures_resolve(doc), "unresolved_figure")
        assert found and "img_068" in found[0].evidence[0]

    def test_a_figure_token_with_its_figure_passes(self):
        doc = document([(1, "One", [
            {"question_number": "1", "question": "Study the figure [image:img_068].",
             "answer": "a", "images": [{"id": "img_068", "file": "x.jpg"}]},
        ])])
        assert quality.check_figures_resolve(doc) == []
