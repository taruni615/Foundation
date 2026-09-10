"""Tests for question/solution mapping, illustration figures and the two sidecars.

The fixtures below reproduce the layout of a real Foundation chapter, including
the OCR damage the parser exists to absorb: exercise numbers mangled to "31"
and "310", headings that lost their ``##``, answer keys flattened onto one line
and typeset in column order, and ``ILLUSTRATIOM`` for ``ILLUSTRATION``.
"""

from __future__ import annotations

import pytest

from edu_pipeline.extraction import question_bank as qb
from edu_pipeline.extraction.topic_extractor import (
    extract_exercise_sections,
    extract_illustrations_from_md,
)
from edu_pipeline.storage.export_qa import (
    build_structured_questions_json,
    build_structured_theory_json,
)


CHAPTER_MD = """\
## WHAT IS LIGHT ?

Light is a form of energy that produces the sensation of vision.

## ILLUSTRATION : 1.1

Two mirrors make an angle of 120° with each other as in Fig. 1.9.

## SOLUTION :

From the law of reflection, the ray makes an angle of 55° with the normal.

![](https://cdn.example.com/fig-1-9.jpg)
Fig. 1.9 Mirrors M1 and M2.

## REFLECTION AT A PLANE MIRROR

A plane mirror forms a virtual and erect image.

ILLUSTRATIOM : 1.2
Find the minimum height of a plane mirror to see one's full image.
SOLUTION :
The required height is half the height of the person.

## CASE STUDY-1 : Nature of the Image

1. The image is virtual.
2. The image is erect.

## Multiple Choice Questions (MCQs)

DIRECTIONS : This section contains multiple choice questions.

1. An object is 0.5 m in front of a plane mirror. Object-image distance is
(a) 0.5 m
(b) 1 m
(c) 0.25 m
(d) 1.5 m
2. Number of images for two mirrors inclined at 90° is
(a) 3
(b) 2
(c) 4
(d) 5
3. In case of erect object having inverted image, magnification is
(a) positive
(b) negative
(c) zero
(d) no definite sign

## Assertion-Reason

1. Assertion : A virtual image cannot be projected on a screen.
2. Assertion : Red light travels faster in glass than green light.

## Exercise 31 Foundation Builder

## Single Option Correct

DIRECTIONS : This section contains multiple choice questions.

1. The critical angle for a medium is 60°. The refractive index is
(a) 1.15
(b) 2.00
(c) 1.41
(d) 1.73
2. A converging beam is incident on a diverging lens.
![](https://cdn.example.com/fig-ex-2.jpg)

## SOLUTIONS <br> (Brief Explanations of Selected Questions)

Exercise 1 Master Boards

Multiple Choice Questions (MCQs)

1. (b) In a plane mirror, object distance = image distance
2. (a) n = 360/90 = 4, so images = 3
3. (b)

Assertion-Reason

1. (a) A virtual image is formed where rays only appear to meet.
2. (c) Red light has the lower refractive index.

Exercise 310 Foundation Builder

Single Option Correct

1. (a) 2. (d)
"""


@pytest.fixture(scope="module")
def sections():
    return extract_exercise_sections(CHAPTER_MD)


@pytest.fixture(scope="module")
def questions(sections):
    return {
        (question["subsection"], question["number"]): question
        for section in sections
        for question in section["questions"]
    }


class TestExerciseLabels:
    def test_exercise_name_survives_mangled_numbering(self):
        """"Exercise 31" and "Exercise 310" are both exercise 3."""
        assert qb.normalize_exercise_label("Exercise 31 Foundation Builder")[0] == (
            qb.normalize_exercise_label("Exercise 310 Foundation Builder")[0]
        )

    def test_foundation_builder_plus_is_not_foundation_builder(self):
        plus, _ = qb.normalize_exercise_label("Exercise 4 : Foundation Builder +")
        plain, _ = qb.normalize_exercise_label("Exercise 3 : Foundation Builder")
        assert plus != plain

    def test_letter_spaced_heading(self):
        assert qb.normalize_exercise_label("1 E X E R C I S E")[0] == "exercise_1"

    @pytest.mark.parametrize(
        ("heading", "kind"),
        [
            ("## Multiple Choice Questions (MCQs)", "mcq"),
            ("Assertion \\& Reason :", "assertion_reason"),
            ("## Very Short Answer Questions", "very_short_answer"),
            ("Short Answer Questions :", "short_answer"),
            ("True / False", "true_false"),
            ("## Text-Book Exercise", "textbook"),
        ],
    )
    def test_subsection_kinds(self, heading, kind):
        assert qb.canonical_subsection_kind(heading) == kind


class TestAnswerKeyLines:
    def test_flattened_key_line_splits(self):
        assert qb.parse_answer_line("1. (a) 2. (b) 3. (a)") == [
            ("1", "(a)"), ("2", "(b)"), ("3", "(a)"),
        ]

    def test_explanation_is_not_split(self):
        """Prose after the option means one answer, not several."""
        assert qb.parse_answer_line(
            "1. (b) In a plane mirror the object distance equals the image distance, "
            "so the total separation is 2. (b) would be wrong here"
        ) == []

    def test_single_answer_is_not_a_key_line(self):
        assert qb.parse_answer_line("1. (b) In plane mirror") == []


class TestQuestionSolutionMapping:
    def test_every_mcq_gets_its_own_answer(self, questions):
        """The answer key sits a chapter away and numbering restarts per block."""
        assert questions[("mcq", "1")]["solution_markdown"].startswith("(b)")
        assert questions[("mcq", "2")]["solution_markdown"].startswith("(a)")
        assert questions[("mcq", "3")]["solution_markdown"].startswith("(b)")

    def test_assertion_reason_numbering_does_not_collide_with_mcq(self, questions):
        """Both blocks number from 1; matching on the number alone mixes them up."""
        assert questions[("assertion_reason", "1")]["solution_markdown"].startswith("(a)")
        assert questions[("mcq", "1")]["solution_markdown"].startswith("(b)")

    def test_answers_from_a_flattened_key_line_are_split_across_questions(self, questions):
        assert questions[("single_option", "1")]["solution_markdown"] == "(a)"
        assert questions[("single_option", "2")]["solution_markdown"] == "(d)"

    def test_exercise_3_answers_do_not_leak_into_exercise_1(self, questions):
        """Exercise 1 MCQ 1 and Exercise 3 Single Option 1 are different questions."""
        assert questions[("mcq", "1")]["solution_markdown"] != (
            questions[("single_option", "1")]["solution_markdown"]
        )

    def test_solutions_half_is_not_emitted_as_questions(self, sections):
        prompts = [q["prompt_markdown"] for s in sections for q in s["questions"]]
        assert not any("object distance = image distance" in p for p in prompts)

    def test_theory_numbered_lists_are_not_questions(self, sections):
        prompts = [q["prompt_markdown"] for s in sections for q in s["questions"]]
        assert not any("The image is virtual." in p for p in prompts)


class TestIllustrations:
    @pytest.fixture(scope="class")
    def illustrations(self):
        return {i["id"]: i for i in extract_illustrations_from_md(CHAPTER_MD)}

    def test_headings_without_markdown_prefix_are_found(self, illustrations):
        """"ILLUSTRATIOM : 1.2" is a plain line and an OCR misspelling."""
        assert set(illustrations) == {"illustration_1_1", "illustration_1_2"}

    def test_problem_and_solution_are_separated(self, illustrations):
        first = illustrations["illustration_1_1"]
        assert "Two mirrors make an angle" in first["problem"]
        assert "law of reflection" in first["solution"]

    def test_figure_in_the_solution_belongs_to_the_illustration(self, illustrations):
        assert illustrations["illustration_1_1"]["image_urls"] == [
            "https://cdn.example.com/fig-1-9.jpg"
        ]

    def test_illustration_does_not_run_on_into_the_next_section(self, illustrations):
        assert "plane mirror forms a virtual" not in illustrations["illustration_1_1"]["solution"]

    def test_numerical_illustration_has_no_figure(self, illustrations):
        assert illustrations["illustration_1_2"]["image_urls"] == []


DOCUMENT = {
    "metadata": {"name": "10 PHYSICS FOUNDATION", "source_file": "10 PHYSICS FOUNDATION.pdf"},
    "topics": [{
        "topic_number": 1,
        "chapter_name": "Light",
        "page_range": "1-40",
        "summary": "Light is a form of energy.",
        "key_points": ["Angle of incidence equals angle of reflection"],
        "theory_sections": [
            {"topics": "What is Light", "markdown": "Light is a form of energy. [image:img_002]"},
        ],
        "image_assets": {
            "img_002": {"source_url": "https://cdn.example.com/a.jpg", "file": "cache/img_002.jpg"},
            "img_007": {"source_url": "https://cdn.example.com/fig.jpg", "file": "cache/img_007.jpg"},
        },
        "illustrations": [{
            "id": "illustration_1_1",
            "question": "Two mirrors make an angle of 120°. [image:img_007]",
            "answer": "55° with the normal.",
        }],
        "exercises": [{"id": "ex_1", "question": "What is a lens?", "answer": "A shaped medium."}],
        # ``examples`` repeats the labelled buckets above; it must not double them.
        "examples": [
            {"id": "illustration_1_1", "question": "Two mirrors make an angle of 120°.",
             "answer": "55° with the normal."},
            {"id": "ex_1", "question": "What is a lens?", "answer": "A shaped medium."},
        ],
    }],
}


class TestStructuredExports:
    @pytest.fixture(scope="class")
    def questions_json(self):
        return build_structured_questions_json(DOCUMENT, "10 PHYSICS FOUNDATION")

    @pytest.fixture(scope="class")
    def theory_json(self):
        return build_structured_theory_json(DOCUMENT, "10 PHYSICS FOUNDATION")

    def test_examples_do_not_duplicate_the_labelled_buckets(self, questions_json):
        questions = questions_json["chapters"][0]["questions"]
        assert len(questions) == 2

    def test_question_carries_its_figure_as_a_path(self, questions_json):
        illustration = questions_json["chapters"][0]["questions"][0]
        assert illustration["images"] == [{
            "id": "img_007",
            "file": "cache/img_007.jpg",
            "source_url": "https://cdn.example.com/fig.jpg",
        }]

    def test_question_without_a_figure_has_an_empty_list(self, questions_json):
        assert questions_json["chapters"][0]["questions"][1]["images"] == []

    def test_no_base64_payload_in_questions_json(self, questions_json):
        assert "base64" not in str(questions_json)

    def test_theory_mirrors_the_questions_envelope(self, questions_json, theory_json):
        assert {k for k in theory_json} - {"chapters"} == {k for k in questions_json} - {"chapters"}
        assert theory_json["class"] == "10"
        assert theory_json["subject"] == "Physics"

    def test_theory_chapter_carries_sections_and_figures(self, theory_json):
        chapter = theory_json["chapters"][0]
        assert chapter["chapter_number"] == 1
        assert chapter["key_points"] == ["Angle of incidence equals angle of reflection"]
        section = chapter["sections"][0]
        assert section["title"] == "What is Light"
        assert section["images"][0]["id"] == "img_002"

    def test_theory_holds_no_questions(self, theory_json):
        assert "questions" not in theory_json["chapters"][0]


class TestHeadingVocabulary:
    """Types the books actually print, including the OCR variants of each."""

    @pytest.mark.parametrize(
        ("heading", "kind"),
        [
            ("More than One Option Correct", "multiple_option"),
            ("One or More than One Option Correct", "multiple_option"),
            ("More than one correct option", "multiple_option"),
            ("## Single Option Correct", "single_option"),
            ("Single Dption Correct", "single_option"),          # OCR: O -> D
            ("## Match the Columns", "matching"),
            ("Match the Column :", "matching"),
            ("## Statement Based Questions", "statement_based"),
            ("Figure/Diagram Based Questions", "diagram_based"),
            ("Integer Type Questions", "integer"),
            ("HOTS Questions", "hots"),
            ("Passage Based Questions", "passage"),
            ("Exemplar Questions", "exemplar"),
        ],
    )
    def test_kinds(self, heading, kind):
        assert qb.canonical_subsection_kind(heading) == kind

    def test_multiple_option_is_not_read_as_single_or_plain_mcq(self):
        """"One or More than One Option Correct" contains both other wordings."""
        assert qb.canonical_subsection_kind("One or More than One Option Correct") not in (
            "single_option", "mcq",
        )

    @pytest.mark.parametrize(
        "banner",
        [
            "## SOLUTIONS <br> (Brief Explanations of Selected Questions)",
            "## Solutions Brief Explanations of Selected Questions",
            "SOLUTIONS",
            "## Solutions",
        ],
    )
    def test_solutions_banner_variants_open_the_answer_half(self, banner):
        """A missed banner makes the whole answer key parse as more questions."""
        assert qb.SOLUTIONS_SPLIT_RE.match(banner)

    @pytest.mark.parametrize("line", ["SOLUTION :", "## SOLUTION", "Solution"])
    def test_singular_solution_is_an_illustration_not_the_key(self, line):
        assert not qb.SOLUTIONS_SPLIT_RE.match(line)

    def test_advanced_exercise_heading(self):
        """OCR drops the space in "AdvancedExercise Based on Connecting Topics"."""
        assert qb._is_exercise_heading("AdvancedExercise Based on Connecting Topics")


class TestDocumentOrder:
    def test_questions_carry_their_line_in_the_source(self):
        blocks = qb.parse_question_bank(CHAPTER_MD)
        lines = [q["source_line"] for b in blocks for q in b["questions"]]
        assert lines == sorted(lines), "parser must emit questions in document order"

    def test_export_orders_questions_as_the_book_prints_them(self):
        """Items are collected bucket by bucket; the export restores the sequence."""
        document = {
            "metadata": {"name": "10 PHYSICS FOUNDATION", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1,
                "chapter_name": "Light",
                # Exercises are gathered before illustrations here, but sit
                # later in the book -- source_order is what decides.
                "exercises": [
                    {"id": "e1", "question": "Exercise question", "answer": "a",
                     "source_order": 900, "subsection_kind": "mcq"},
                ],
                "illustrations": [
                    {"id": "i1", "question": "Illustration question", "answer": "x",
                     "source_order": 100},
                ],
                "check_your_knowledge_items": [
                    {"id": "c1", "question": "Check your knowledge question", "answer": "y",
                     "source_order": 50},
                ],
            }],
        }
        out = build_structured_questions_json(document, "10 PHYSICS FOUNDATION")
        got = [q["question"] for q in out["chapters"][0]["questions"]]
        assert got == [
            "Check your knowledge question",
            "Illustration question",
            "Exercise question",
        ]
        numbers = [q["question_number"] for q in out["chapters"][0]["questions"]]
        assert numbers == ["1", "2", "3"], "numbering follows the restored order"


class TestQuestionTypeFromHeading:
    def _export(self, kind, question="What is the focal length?"):
        document = {
            "metadata": {"name": "10 PHYSICS FOUNDATION", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1,
                "chapter_name": "Light",
                "exercises": [{
                    "id": "q1", "question": question, "answer": "a",
                    "subsection_kind": kind, "subsection_title": "heading",
                    "source_order": 1,
                }],
            }],
        }
        return build_structured_questions_json(document, "x")["chapters"][0]["questions"][0]

    @pytest.mark.parametrize(
        ("kind", "label"),
        [
            ("mcq", "MCQ"),
            ("single_option", "MCQ (Single Correct)"),
            ("multiple_option", "MCQ (Multiple Correct)"),
            ("assertion_reason", "Assertion-Reason"),
            ("fill_blanks", "Fill in the Blanks"),
            ("true_false", "True/False"),
            ("matching", "Matching"),
            ("integer", "Integer"),
            ("hots", "HOTS"),
            ("textbook", "Textbook Question"),
        ],
    )
    def test_type_comes_from_the_heading(self, kind, label):
        assert self._export(kind)["question_type"] == label

    def test_heading_beats_the_wording_based_guess(self):
        """An MCQ under a Fill in the Blanks heading is a Fill in the Blanks."""
        q = self._export("fill_blanks", "The power of a lens is ____ (a) x (b) y (c) z (d) w")
        assert q["question_type"] == "Fill in the Blanks"

    def test_unheaded_items_still_get_a_type(self):
        """Illustrations carry no heading, so they fall back to classification."""
        document = {
            "metadata": {"name": "10 PHYSICS FOUNDATION", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1, "chapter_name": "Light",
                "illustrations": [{"id": "i1", "question": "Find the focal length.",
                                   "answer": "10 cm", "source_order": 1}],
            }],
        }
        q = build_structured_questions_json(document, "x")["chapters"][0]["questions"][0]
        assert q["question_type"] and q["question_type"] != "General"

    def test_heading_is_reported_on_the_source(self):
        assert self._export("mcq")["source"]["heading"] == "heading"


class TestChapterSplitting:
    """Locating where each chapter starts, on OCR that mangles the titles.

    Getting this wrong is expensive: a chapter whose start is missed has its
    content folded into its neighbour, so its questions are attributed to the
    wrong chapter or dropped with it.
    """

    def _meta(self, number, name, pages="1-30"):
        from edu_pipeline.extraction.topic_extractor import TopicMeta
        return TopicMeta(topic_number=number, topic_name=name, page_range=pages)

    def test_char_similarity_sees_through_ocr_damage(self):
        """"NUTRITIONIN ANMALS" lost a space and a letter; no word lines up."""
        from edu_pipeline.extraction.topic_extractor import title_char_similarity
        assert title_char_similarity("Nutrition in Animals", "NUTRITIONIN ANMALS") > 0.9
        assert title_char_similarity("Nutrition in Animals", "MODE OF NUTRITION IN PLANTS") < 0.8

    def test_real_title_outranks_a_shouted_subheading(self):
        """The mixed-case rule caps long titles at 82; an exact match must survive it."""
        from edu_pipeline.extraction.topic_extractor import score_topic_start_candidate
        meta = self._meta(2, "Linear Equations in One Variable")
        real = score_topic_start_candidate("## Linear Equations in One Variable", meta)
        decoy = score_topic_start_candidate(
            "## SOLUTION OF A LINEAR EQUATION OF ONE VARIABLE", meta)
        assert real > decoy

    def test_ocr_mangled_title_outranks_a_similar_section(self):
        from edu_pipeline.extraction.topic_extractor import score_topic_start_candidate
        meta = self._meta(2, "Nutrition in Animals")
        real = score_topic_start_candidate("## NUTRITIONIN ANMALS", meta)
        decoy = score_topic_start_candidate("## MODE OF NUTRITION IN PLANTS", meta)
        assert real > decoy

    def test_chapter_aliases_need_the_books_own_contents_to_agree(self):
        """The alias numbers come from a class-10 Biology book.

        Without this check "chapter 1 is Life Processes" hijacks chapter 1 of
        every book, and one of them loses most of its content to the wrong split.
        """
        from edu_pipeline.extraction.topic_extractor import _title_matches_topic_aliases
        assert _title_matches_topic_aliases(1, "LIFE PROCESSES", "Life Processes")
        assert not _title_matches_topic_aliases(
            1, "LIFE PROCESSES", "Crop Production \\& Management")

    def test_explicit_chapter_marker_counts_as_a_boundary(self):
        """11 of the 16 books print a plain "## Chapter 2" above the title."""
        from edu_pipeline.extraction.topic_extractor import near_chapter_boundary
        lines = ["text", "## Chapter 2", "", "## NUTRITIONIN ANMALS", "more"]
        assert near_chapter_boundary(lines, 3)
        assert not near_chapter_boundary(["a", "b", "## SOME SECTION", "c"], 2)


class TestMathConversion:
    """LaTeX → MathML, where two artefacts used to reach the reader."""

    def test_alignment_character_does_not_become_a_glyph(self):
        """latex2mathml renders an ``aligned`` column separator as <mi>&</mi>.

        Mathpix wraps every multi-line derivation in ``aligned``, so left alone
        this puts a stray character in front of thousands of equations.
        """
        from edu_pipeline.extraction.topic_extractor import MathConverter
        out = MathConverter().latex_to_mathml(
            r"\begin{aligned} & -n=\frac{-f}{-(f-u)} \\ & -nu=-f-nf \end{aligned}")
        assert "<mi>&</mi>" not in out
        assert "mfrac" in out, "the maths itself must survive"

    def test_no_bare_ampersand_survives(self):
        """A bare & is not an entity, so it also makes the MathML invalid XML."""
        import re as _re
        from edu_pipeline.extraction.topic_extractor import MathConverter
        out = MathConverter().latex_to_mathml(r"\begin{aligned} & a=b \\ & c=d \end{aligned}")
        assert not _re.search(r"&(?![a-zA-Z#])", out)

    def test_matrix_cells_are_left_alone(self):
        """matrix uses & to separate real cells and latex2mathml handles it."""
        from edu_pipeline.extraction.topic_extractor import MathConverter
        out = MathConverter().latex_to_mathml(r"\begin{matrix} a & b \\ c & d \end{matrix}")
        assert out.count("<mtd>") == 4

    def test_escaped_ampersand_is_content_and_is_kept(self):
        from edu_pipeline.extraction.topic_extractor import MathConverter
        assert "&#x00026;" in MathConverter().latex_to_mathml(r"a \& b")

    def test_conversion_is_idempotent(self):
        """It runs twice on the merge path.

        An unbalanced ``$`` otherwise pairs with a later one, swallows the
        MathML between them and re-converts it -- the literal text ``<math``
        comes back typeset as maths and the document ends up with more
        ``</math>`` tags than ``<math>`` ones.
        """
        from edu_pipeline.extraction.topic_extractor import MathConverter
        converter = MathConverter()
        source = r"We know $\frac{1}{f}=\frac{1}{v}$ or $f=1.2$ m and a stray $ here"
        once = converter.convert_text(source)
        assert converter.convert_text(once) == once
        assert once.count("<math") == once.count("</math>")


class TestMatchingQuestions:
    MATCH_MD = """Match List I with List II.
List I
(A) Power of convex mirror
(B) Power of concave mirror
List II
(p) negative
(q) positive
(a) A-q, B-p
(b) A-p, B-q"""

    def test_lists_are_split_out_with_their_labels(self):
        from edu_pipeline.storage.export_qa import parse_matching_question
        parsed = parse_matching_question(self.MATCH_MD)
        assert parsed["question"] == "Match List I with List II."
        assert parsed["list_1"] == [
            {"id": "A", "text": "Power of convex mirror"},
            {"id": "B", "text": "Power of concave mirror"},
        ]
        assert [i["id"] for i in parsed["list_2"]] == ["p", "q"]

    def test_combination_options_are_not_read_as_list_entries(self):
        """(a)-(d) look like Column II labels; their pairing text tells them apart."""
        from edu_pipeline.storage.export_qa import parse_matching_question
        parsed = parse_matching_question(self.MATCH_MD)
        assert [o["id"] for o in parsed["options"]] == ["a", "b"]
        assert all(i["id"] not in ("a", "b") for i in parsed["list_2"])

    def test_column_wording_is_handled_too(self):
        from edu_pipeline.storage.export_qa import parse_matching_question
        parsed = parse_matching_question(
            "Match the following :\nColumn I\n(A) x\nColumn II\n(p) y")
        assert parsed["list_1"][0]["id"] == "A"
        assert parsed["list_2"][0]["id"] == "p"

    def test_answer_names_the_option_when_there_are_options(self):
        from edu_pipeline.storage.export_qa import parse_matching_question, parse_matching_answer
        parsed = parse_matching_question(self.MATCH_MD)
        assert parse_matching_answer("(b)", parsed["options"]) == "b"

    def test_answer_is_the_pairing_when_there_are_no_options(self):
        from edu_pipeline.storage.export_qa import parse_matching_answer
        assert parse_matching_answer("A-q, B-p", []) == {"A": "q", "B": "p"}

    def test_plain_text_is_not_forced_into_a_matching_shape(self):
        from edu_pipeline.storage.export_qa import parse_matching_question
        assert parse_matching_question("What is the focal length of a lens?") is None

    def test_export_emits_the_lists_on_the_question(self):
        from edu_pipeline.storage.export_qa import build_structured_questions_json
        document = {
            "metadata": {"name": "10 PHYSICS FOUNDATION", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1, "chapter_name": "Light",
                "exercises": [{
                    "id": "m1", "question": self.MATCH_MD, "answer": "(b)",
                    "subsection_kind": "matching", "source_order": 1,
                }],
            }],
        }
        q = build_structured_questions_json(document, "x")["chapters"][0]["questions"][0]
        assert q["question_type"] == "Matching"
        assert [i["id"] for i in q["list_1"]] == ["A", "B"]
        assert [i["id"] for i in q["list_2"]] == ["p", "q"]
        assert [o["id"] for o in q["options"]] == ["a", "b"]
        assert q["answer"] == "b"


class TestPassageQuestions:
    BANK = """## Multiple Choice Questions (MCQs)

1. A plane mirror forms which image?
(a) real
(b) virtual

## Passage Based Questions
DIRECTIONS : Study the given passage and answer the following questions.

Passage
A 5.0 cm tall object is placed perpendicular to the axis of a convex lens.
The distance of the object from the lens is 30 cm.

1. What is the distance of image from the pole of lens?
(a) 60 cm

2. What is the power of the used lens?
(a) +5 D

Passage - II
A concave mirror has focal length 15 cm.

3. Where is the image?
(a) 30 cm

## Very Short Answer Questions

1. What is reflection of light?
"""

    def _questions(self):
        return {
            (block["subsection_kind"], q["number"]): q
            for block in qb.parse_question_bank(self.BANK)
            for q in block["questions"]
        }

    def test_passage_is_carried_onto_every_question_under_it(self):
        """The passage belongs to the run of questions, not to the first one."""
        found = self._questions()
        assert "convex lens" in found[("passage", "1")]["passage"]
        assert found[("passage", "1")]["passage"] == found[("passage", "2")]["passage"]

    def test_a_second_passage_takes_over(self):
        found = self._questions()
        assert "concave mirror" in found[("passage", "3")]["passage"]
        assert "convex lens" not in found[("passage", "3")]["passage"]

    def test_passage_does_not_leak_into_other_sections(self):
        found = self._questions()
        assert found[("mcq", "1")]["passage"] == ""
        assert found[("very_short_answer", "1")]["passage"] == ""

    def test_passage_is_not_swallowed_into_the_first_question(self):
        found = self._questions()
        assert "5.0 cm tall object" not in found[("passage", "1")]["prompt_markdown"]

    def test_export_emits_it_as_question_stem(self):
        document = {
            "metadata": {"name": "10 PHYSICS FOUNDATION", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1, "chapter_name": "Light",
                "exercises": [{
                    "id": "p1", "question": "What is the image distance?",
                    "answer": "a", "subsection_kind": "passage",
                    "passage": "A 5.0 cm tall object is placed before a convex lens.",
                    "source_order": 1,
                }],
            }],
        }
        q = build_structured_questions_json(document, "x")["chapters"][0]["questions"][0]
        assert q["question_stem"] == "A 5.0 cm tall object is placed before a convex lens."
        assert q["question"] == "What is the image distance?"

    def test_questions_without_a_passage_have_no_stem_field(self):
        document = {
            "metadata": {"name": "b", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1, "chapter_name": "Light",
                "exercises": [{"id": "x1", "question": "What is a lens?", "answer": "a",
                               "subsection_kind": "mcq", "source_order": 1}],
            }],
        }
        q = build_structured_questions_json(document, "x")["chapters"][0]["questions"][0]
        assert "question_stem" not in q


class TestMatchingKinds:
    def test_multiple_matching_is_its_own_kind(self):
        """Sharing the "matching" kind lets one section eat the other's key.

        102 chapters print both headings, so the answers crossed over.
        """
        assert qb.canonical_subsection_kind("Multiple Matching Questions") == "multiple_matching"
        assert qb.canonical_subsection_kind("Match the Following") == "matching"

    def test_image_url_is_not_mistaken_for_pairing_options(self):
        """A hex image id ("...4fb7-410b...") is full of letter-digit pairs."""
        from edu_pipeline.storage.export_qa import _looks_like_pairing_option
        assert not _looks_like_pairing_option(
            "![](https://cdn.mathpix.com/cropped/340ec80c-4fb7-410b-95cb-cc867b466998-046.jpg)")
        assert _looks_like_pairing_option("A-q, B-p, C-s, D-r")

    def test_label_running_into_its_text_is_still_split(self):
        """A matching table flattened out of HTML loses the space."""
        from edu_pipeline.storage.export_qa import parse_matching_question
        parsed = parse_matching_question(
            "Match them. Column I(A)Acceleration(B)Velocity Column II(p)may be zero(q)is zero")
        assert [i["id"] for i in parsed["list_1"]] == ["A", "B"]
        assert [i["id"] for i in parsed["list_2"]] == ["p", "q"]

    def test_answers_pair_positionally_when_numbering_restarts(self):
        """Questions numbered 29, 30 whose answers restart at 1, 2."""
        # An MCQ heading opens the bank: "matching" alone is not treated as a
        # bank start, because theory carries matching-shaped lists of its own.
        md = ("## Multiple Choice Questions (MCQs)\n\n1. Warm up?\n(a) yes\n\n"
              "## Multiple Matching Questions\n\n29. First one\n30. Second one\n\n"
              "## SOLUTIONS\n\nMultiple Matching Questions\n\n1. (b)\n2. (d)\n")
        found = {q["number"]: q["solution_markdown"]
                 for b in qb.parse_question_bank(md) for q in b["questions"]}
        assert found["29"] == "(b)"
        assert found["30"] == "(d)"


class TestPageFurnitureIsNotContent:
    """The books print furniture around their questions; none of it is a question.

    Every case here comes from a real chapter: an exam credit inline in the
    stem, a Check Your Knowledge sidebar with no closing marker, an answer that
    ran on into the next exercise's DIRECTIONS preamble.
    """

    def test_exam_tag_moves_out_of_the_stem(self):
        from edu_pipeline.storage.export_qa import sanitize_question_text
        text, tags = sanitize_question_text(
            "Chemically the 'water gas' is [JSTSE] (a) H2O (b) CO2")
        assert text == "Chemically the 'water gas' is (a) H2O (b) CO2"
        assert tags == ["JSTSE"]

    def test_exam_tag_is_recorded_on_the_exported_question(self):
        document = {
            "metadata": {"name": "Book", "source_file": "b.pdf"},
            "topics": [{
                "topic_number": 1,
                "chapter_name": "Acids",
                "exercises": [{"id": "e1", "question": "Water gas is [NTSE] hot",
                               "answer": "a", "source_order": 1}],
            }],
        }
        out = build_structured_questions_json(document, "Book")
        question = out["chapters"][0]["questions"][0]
        assert question["question"] == "Water gas is hot"
        assert question["source"]["exam"] == ["NTSE"]

    @pytest.mark.parametrize("banner", [
        "Time to Check Your Knowledge",
        "→ Time to Check Your Knowledge",
        "Time to\nCheck Your\nKnowledge",
        "Check Your Check Your Knowledge Knowledge",
    ])
    def test_banner_above_a_prompt_is_dropped(self, banner):
        from edu_pipeline.storage.export_qa import sanitize_question_text
        text, _ = sanitize_question_text(f"{banner}\n\n- Will he get plaster of paris?")
        assert text == "Will he get plaster of paris?"

    def test_a_question_may_still_say_check_your_knowledge(self):
        """Only a banner on its own line is furniture; wording is content."""
        from edu_pipeline.storage.export_qa import sanitize_question_text
        text, _ = sanitize_question_text("Check your knowledge of acids and bases.")
        assert text == "Check your knowledge of acids and bases."

    def test_answer_running_into_the_next_exercise_is_cut(self):
        from edu_pipeline.storage.export_qa import sanitize_question_text
        text, _ = sanitize_question_text(
            "Nascent oxygen is responsible for disinfection of water.\n\n"
            "Multiple Choice Questions (MCQs)\n"
            "DIRECTIONS : This section contains multiple choice questions.")
        assert text == "Nascent oxygen is responsible for disinfection of water."

    def test_a_block_that_opens_on_directions_keeps_it(self):
        """A bare DIRECTIONS line names an exercise; it is not a run-on."""
        from edu_pipeline.storage.export_qa import sanitize_question_text
        source = "DIRECTIONS (Qs. 1-32) : Answer the following.\n1. What is an acid?"
        assert sanitize_question_text(source)[0] == source

    def test_an_option_is_never_mistaken_for_a_heading(self):
        from edu_pipeline.storage.export_qa import sanitize_question_text
        text, _ = sanitize_question_text(
            "(d) activation energy\n\\section*{More than One Option Correct}\nDIRECTIONS : x")
        assert text == "(d) activation energy"

    def test_matched_display_math_survives(self):
        """An unpaired $$ is OCR debris; a matched pair is the equation."""
        from edu_pipeline.storage.export_qa import sanitize_question_text
        source = "Reaction:\n$$ 2KOH + H_2SO_4 $$\nis complete."
        assert sanitize_question_text(source)[0] == source
        assert sanitize_question_text("Value is $$ 5 and rises.")[0] == "Value is 5 and rises."

    def test_table_separator_rows_are_not_question_numbers(self):
        assert qb.TABLE_RULE_RE.match("| :--- | :---: |")
        assert not qb.TABLE_RULE_RE.match("| a | b |")

    def test_fullwidth_numbering_starts_a_new_question(self):
        """Mathpix emits "５．" for "5." on some pages -- 554 lines of the corpus."""
        assert qb.NUMBERED_RE.match("５．Balance it")
        assert qb.normalize_number("５") == "5"

    def test_a_sentence_is_not_a_subsection_heading(self):
        """This one opened a bogus sub-section that swallowed 15,509 chars."""
        assert not qb._looks_like_heading(
            "After substituting numerical values in Eq.(7), we obtain")
        assert qb._looks_like_heading("More than One Option Correct")
        assert qb._looks_like_heading("Fill in the Blanks")


class TestChapterBoundaries:
    """A missed chapter costs the whole chapter: it folds into its neighbour."""

    def test_contents_table_rows_are_chapters(self):
        """Chemistry class 10 prints chapters 1-3 dotted and 4-9 as table rows."""
        from edu_pipeline.extraction.topic_extractor import parse_contents_topics
        lines = [
            "## CONTENTS",
            "",
            "1. Chemical Reactions and Equations ..... 1-46",
            "| 4. | Carbon and its Compounds | 145-194 |",
            "| :--- | :--- | :--- |",
            "|  | Concept Map Detailed theory Exercise 1 : Master Boards |  |",
            "| 5. | Periodic Classificationof Elements | 195-236 |",
        ]
        found = [(t.topic_number, t.topic_name) for t in parse_contents_topics(lines)]
        assert found == [
            (1, "Chemical Reactions and Equations"),
            (4, "Carbon and its Compounds"),
            (5, "Periodic Classificationof Elements"),
        ]

    def test_theory_resuming_ends_a_sidebar_box(self):
        """A Check Your Knowledge answer otherwise runs to the end of the chapter."""
        from edu_pipeline.extraction.topic_extractor import (
            extract_check_your_knowledge_pairs,
        )
        md = (
            "Time to Check Your Knowledge\n\n"
            "* Write the structure of compound neononane ?\n\n"
            "SOLUTION\n"
            "Neo indicates a tertiary butyl group and nonane nine carbon atoms.\n"
            "(b) Alkenes or Olefins (Unsaturated Hydrocarbons) :\n"
            "These are characterised by the presence of a double bond between two carbons.\n"
        )
        pairs = extract_check_your_knowledge_pairs(md)
        assert len(pairs) == 1
        assert "Alkenes" not in pairs[0]["solution"]
        assert "Neo indicates" in pairs[0]["solution"]

    def test_illustration_solution_stops_where_the_theory_resumes(self):
        md = (
            "ILLUSTRATION : 2\n"
            "How NaCN acts as a depressant?\n"
            "SOLUTION\n"
            "NaCN forms a complex with ZnS and prevents it from forming froth.\n"
            "(c) Electromagnetic separation : This method is used for ores that are\n"
            "magnetic in nature and can be separated from the gangue particles.\n"
        )
        solution = extract_illustrations_from_md(md)[0]["solution"]
        assert "prevents it from forming froth" in solution
        assert "Electromagnetic" not in solution


class TestBannerlessAnswerKey:
    """Some chapters lose the SOLUTIONS banner entirely in OCR.

    Maths chapter 2 has no "SOLUTIONS" line anywhere, so its whole answer key
    parsed as 243 more questions -- the chapter reported 255 questions with 12
    answers. The key still *looks* like a key.
    """

    KEY = ("1. (b) The highest power of x is two.\n"
           "2. (a) Substitute x = 1 into p(x).\n"
           "3. (d) Substitute y = 1\n"
           "4. (a) Substitute x = 3 in the polynomial\n"
           "5. (b) Equate the value at x = a with a\n")
    QUESTIONS = ("## Multiple Choice Questions (MCQs)\n\n"
                 "1. What is the degree of the polynomial?\n(a) 1\n(b) 2\n"
                 "2. Which is a zero of p(x)?\n(a) 1\n(b) 3\n\n")

    def test_a_key_without_a_banner_is_not_read_as_questions(self):
        """The damage is not the missing answers -- it is the phantom questions."""
        blocks = qb.parse_question_bank(self.QUESTIONS + self.KEY)
        numbers = [q["number"] for b in blocks for q in b["questions"]]
        assert numbers == ["1", "2"], "the key must not become three more questions"

    def test_a_bannerless_key_still_answers_when_it_names_its_section(self):
        md = self.QUESTIONS + "Multiple Choice Questions (MCQs)\n" + self.KEY
        found = {q["number"]: q["solution_markdown"]
                 for b in qb.parse_question_bank(md) for q in b["questions"]}
        assert found.get("1", "").startswith("(b)")
        assert found.get("2", "").startswith("(a)")

    def test_an_option_list_is_not_mistaken_for_a_key(self):
        """Questions put one option per line; a key puts the number and key together."""
        lines = ["1. What is the degree?", "(a) 1", "(b) 2", "(c) 3", "(d) 4",
                 "2. Which is a zero?", "(a) 1", "(b) 3", "(c) 5", "(d) 7"]
        assert qb.find_answer_key_start(lines) is None

    def test_a_short_run_is_not_a_key(self):
        lines = ["1. (a) yes", "2. (b) no", "Some prose about the topic follows here."]
        assert qb.find_answer_key_start(lines) is None


class TestSolutionMarkerCarriesContent:
    """"SOLUTION: (i)" puts the first line of the answer on the marker's line."""

    def test_content_after_the_marker_starts_the_solution(self):
        md = ("ILLUSTRATION : 1\n"
              "Derive the dimensional formula for pressure.\n"
              "SOLUTION: (i) Pressure = Force / Area\n"
              "So the dimensions are M L^-1 T^-2.\n")
        found = extract_illustrations_from_md(md)[0]
        assert "Pressure = Force / Area" in found["solution"]
        assert "SOLUTION" not in found["problem"]
        assert "Pressure = Force" not in found["problem"]

    def test_a_theory_heading_beginning_with_solution_is_not_a_marker(self):
        """"SOLUTION OF A PAIR OF LINEAR EQUATIONS" opens a section, not an answer."""
        from edu_pipeline.extraction.topic_extractor import SOLUTION_RE

        assert not SOLUTION_RE.match("SOLUTION OF A PAIR OF LINEAR EQUATIONS")
        assert not SOLUTION_RE.match("## SOLUTION OF A PAIR OF LINEAR EQUATIONS")
        assert SOLUTION_RE.match("SOLUTION")
        assert SOLUTION_RE.match("SOLUTION: (i)").group("rest") == "(i)"


class TestUnlabelledAnswerKey:
    """Some keys name neither their exercise nor their sub-section.

    Chemistry class 9 chapter 6 prints a bare list under "## Solutions"; with
    no coordinate to match on, all 55 questions came back unanswered.
    """

    def test_a_key_with_no_headings_matches_on_its_numbers(self):
        md = ("## Multiple Choice Questions (MCQs)\n\n"
              "1. What is a polymer?\n(a) one\n(b) two\n"
              "2. What is DNA?\n(a) one\n(b) two\n"
              "3. What is PVC?\n(a) one\n(b) two\n"
              "4. What is lactose?\n(a) one\n(b) two\n\n"
              "## Solutions\n\n"
              "1. (d)\n2. (d) Deoxyribonucleic acid is a polymer.\n"
              "3. (c) Obtained by addition polymerisation.\n4. (a) Milk sugar.\n")
        found = {q["number"]: q["solution_markdown"]
                 for b in qb.parse_question_bank(md) for q in b["questions"]}
        assert found["1"].startswith("(d)")
        assert found["4"].startswith("(a)")

    def test_numbers_that_do_not_line_up_are_left_unanswered(self):
        """Matching on bare numbers alone is what misaligned the bank originally."""
        md = ("## Multiple Choice Questions (MCQs)\n\n"
              "1. What is a polymer?\n(a) one\n(b) two\n"
              "2. What is DNA?\n(a) one\n(b) two\n"
              "3. What is PVC?\n(a) one\n(b) two\n\n"
              "## Solutions\n\n"
              "41. (d)\n42. (d) Something else.\n43. (c) A third thing.\n")
        found = {q["number"]: q["solution_markdown"]
                 for b in qb.parse_question_bank(md) for q in b["questions"]}
        assert not any(v.strip() for v in found.values())
