"""Unit tests for build_structured_questions_json target schema formatting."""

from __future__ import annotations

import json
from edu_pipeline.storage.export_qa import build_structured_questions_json


def test_build_structured_questions_json_schema():
    dummy_doc = {
        "metadata": {
            "name": "10 PHYSICS FOUNDATION",
            "source_file": "10 PHYSICS FOUNDATION.pdf",
        },
        "topics": [
            {
                "topic_number": 1,
                "topic_name": "Light-Reflection and Refraction",
                "pdf_page_number": 35,
                "printed_page_number": 31,
                "textbook_exercises": [
                    {
                        "question": "What is the nature of the image formed by a concave mirror if the magnification produced by the mirror is +3? (a) Real and inverted (b) Virtual and erect (c) Real and erect (d) Virtual and inverted",
                        "answer": "(b) Virtual and erect",
                        "explanation": "A positive magnification indicates that the image is virtual and erect.",
                    },
                    {
                        "question": "An object is placed at a distance of 20 cm from a concave mirror. Calculate the focal length.",
                        "answer": "10",
                        "question_type": "Integer",
                    },
                    {
                        "question": "Match the following: Column 1 Column 2 A. Concave mirror B. Convex mirror 1. Virtual 2. Real",
                        "answer": "A -> 2, B -> 1",
                        "question_type": "Matching",
                    }
                ],
            }
        ],
    }

    res = build_structured_questions_json(dummy_doc, "10 PHYSICS FOUNDATION")

    assert res["class"] == "10"
    assert res["subject"] == "Physics"
    assert res["book_name"] == "10 PHYSICS FOUNDATION"
    assert res["source_file"] == "10 PHYSICS FOUNDATION.pdf"
    assert len(res["chapters"]) == 1

    ch = res["chapters"][0]
    assert ch["chapter_number"] == 1
    assert ch["chapter_name"] == "Light-Reflection and Refraction"
    assert len(ch["questions"]) == 3

    # Question 1 (MCQ). These fixture items carry no heading, so the type is
    # classified from the wording; a multiple-choice question is now reported as
    # "MCQ" rather than being collapsed into "General".
    q1 = ch["questions"][0]
    assert q1["question_number"] == "1"
    assert q1["question_type"] == "MCQ"
    assert q1["source"]["file_name"] == "10 PHYSICS FOUNDATION.pdf"
    assert q1["source"]["pdf_page_number"] == 35
    assert q1["source"]["printed_page_number"] == 31
    assert q1["options"] == {
        "a": "Real and inverted",
        "b": "Virtual and erect",
        "c": "Real and erect",
        "d": "Virtual and inverted",
    }
    assert q1["answer"] == "b"

    # Question 2 (Integer)
    q2 = ch["questions"][1]
    assert q2["question_number"] == "2"
    assert q2["question_type"] == "Integer"
    assert q2["options"] is None
    assert q2["answer"] == "10"

    # Question 3 (Matching)
    q3 = ch["questions"][2]
    assert q3["question_number"] == "3"
    assert q3["question_type"] == "Matching"
    # Matching questions now carry their two lists as first-class fields;
    # options[] holds combination choices ("A-2, B-1") and is empty when the
    # book expects a direct pairing, as here.
    assert q3["list_1"] == [
        {"id": "A", "text": "Concave mirror"},
        {"id": "B", "text": "Convex mirror"},
    ]
    assert q3["list_2"] == [
        {"id": "1", "text": "Virtual"},
        {"id": "2", "text": "Real"},
    ]
    assert q3["options"] == []
    assert q3["answer"] == {"A": "2", "B": "1"}
