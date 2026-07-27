"""Repository layer: loading, saving, querying and validating book documents."""

from __future__ import annotations

import json

import pytest

from edu_pipeline.repository import BookRepository, RepositoryService


class TestResolveAndLoad:
    def test_resolves_slug_within_a_workspace(self, workspace):
        path = RepositoryService.resolve_path("10 TEST FOUNDATION", str(workspace))
        assert path.endswith("10 TEST FOUNDATION_final.json")

    def test_resolves_a_direct_file_path(self, workspace):
        direct = workspace / "10 TEST FOUNDATION" / "10 TEST FOUNDATION_final.json"
        assert RepositoryService.resolve_path(str(direct)) == str(direct.resolve())

    def test_unknown_book_raises_file_not_found(self, workspace):
        with pytest.raises(FileNotFoundError):
            RepositoryService.resolve_path("NO SUCH BOOK", str(workspace))

    def test_load_exposes_metadata_and_topics(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        assert isinstance(repo, BookRepository)
        assert repo.metadata["name"] == "10 TEST FOUNDATION"
        assert len(repo.topics) == 2
        assert repo.source_path is not None

    def test_list_books_finds_only_extracted_books(self, workspace):
        (workspace / "EMPTY BOOK").mkdir()
        assert RepositoryService.list_books(str(workspace)) == ["10 TEST FOUNDATION"]

    def test_list_books_on_missing_directory_returns_empty(self, tmp_path):
        assert RepositoryService.list_books(str(tmp_path / "absent")) == []


class TestQueries:
    def test_get_topics_returns_every_topic(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        assert [t["topic_number"] for t in RepositoryService.get_topics(repo)] == [1, 2]

    def test_get_theory_flattens_and_tags_with_chapter(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        theory = RepositoryService.get_theory(repo)
        assert len(theory) == 3
        assert {t["chapter_name"] for t in theory} == {"Reflection of Light", "Refraction"}
        assert all("topic_number" in t for t in theory)

    def test_get_questions_covers_every_qa_section(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        questions = RepositoryService.get_questions(repo)
        assert len(questions) == 3
        assert {q["section_key"] for q in questions} == {
            "illustrations", "textbook_exercises", "exercises"
        }

    def test_find_topic_and_alias_agree(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        assert RepositoryService.find_topic(repo, 2)["chapter_name"] == "Refraction"
        assert RepositoryService.get_topic(repo, 2) == RepositoryService.find_topic(repo, 2)
        assert RepositoryService.find_topic(repo, 99) is None

    def test_find_question_matches_question_and_answer_text(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        assert len(RepositoryService.find_question(repo, "refractive index")) == 1
        assert len(RepositoryService.find_question(repo, "angle i = angle r")) == 1  # answer text
        assert RepositoryService.find_question(repo, "") == []
        assert RepositoryService.find_question(repo, "zzz") == []

    def test_queries_do_not_mutate_the_document(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        before = json.dumps(repo.raw_json, sort_keys=True)
        RepositoryService.get_questions(repo)
        RepositoryService.get_theory(repo)
        assert json.dumps(repo.raw_json, sort_keys=True) == before


class TestTheoryTextExtraction:
    """Regression guard for the defect that silently emptied the notes pipeline.

    Real v3.1 documents store section bodies under "markdown". Callers that read
    only excerpt/content/text produced a string of empty "## " headings, which
    is truthy — so the notes model received no source material and hallucinated
    the entire chapter.
    """

    def test_reads_the_v31_markdown_field(self):
        topic = {"theory_sections": [
            {"markdown": "Light travels in straight lines.", "topics": []},
            {"markdown": "The angle of incidence equals the angle of reflection.", "topics": []},
        ]}
        text = RepositoryService.get_topic_theory_text(topic)
        assert "straight lines" in text
        assert "angle of incidence" in text

    def test_still_reads_legacy_excerpt_and_heading_fields(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        text = RepositoryService.get_topic_theory_text(repo.topics[0])
        assert "Laws of Reflection" in text
        assert "angle of incidence" in text.lower()

    def test_never_returns_only_empty_headings(self):
        topic = {"theory_sections": [{"markdown": "", "topics": []},
                                     {"markdown": "", "topics": []}]}
        text = RepositoryService.get_topic_theory_text(topic)
        assert text.replace("#", "").strip() == "", "must not fabricate heading scaffolding"
        assert len(text.strip()) < 40, "empty sections must fall below the usable-theory floor"

    def test_falls_back_to_topic_level_fields(self):
        topic = {"theory_sections": [], "theory_notes_preview": "Fallback theory body."}
        assert "Fallback theory body." in RepositoryService.get_topic_theory_text(topic)

    def test_returns_empty_for_a_topic_with_no_theory(self):
        assert RepositoryService.get_topic_theory_text({}) == ""

    def test_extracts_real_theory_from_the_shipped_book(self):
        books = RepositoryService.list_books()
        if not books:
            pytest.skip("no extracted book available")
        repo = RepositoryService.load(books[0])
        lengths = [len(RepositoryService.get_topic_theory_text(t)) for t in repo.topics]
        assert all(n > 1000 for n in lengths), f"topics with no theory: {lengths}"


class TestSaveAndReload:
    def test_save_then_load_round_trips(self, workspace, tmp_path):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        target = tmp_path / "out" / "book.json"
        RepositoryService.save(repo, str(target))
        assert target.is_file()
        assert json.loads(target.read_text(encoding="utf-8"))["metadata"]["name"] == "10 TEST FOUNDATION"

    def test_save_without_target_raises(self):
        with pytest.raises(ValueError):
            RepositoryService.save(BookRepository(raw_json={"a": 1}))

    def test_reload_picks_up_external_changes(self, workspace):
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        doc = json.loads(open(repo.source_path, encoding="utf-8").read())
        doc["metadata"]["name"] = "RENAMED"
        open(repo.source_path, "w", encoding="utf-8").write(json.dumps(doc))
        assert RepositoryService.reload(repo).metadata["name"] == "RENAMED"


class TestValidate:
    def test_valid_document_reports_no_errors(self, workspace):
        result = RepositoryService.validate(RepositoryService.load("10 TEST FOUNDATION", str(workspace)))
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["topic_count"] == 2

    def test_empty_document_is_invalid(self):
        result = RepositoryService.validate(BookRepository())
        assert result["valid"] is False
        assert result["errors"]

    def test_topic_without_number_is_warned_not_failed(self):
        repo = BookRepository(raw_json={"metadata": {"name": "x"}, "topics": [{"chapter_name": "n"}]})
        result = RepositoryService.validate(repo)
        assert result["valid"] is True
        assert any("topic_number" in w for w in result["warnings"])


class TestLayering:
    def test_repository_does_not_depend_on_extraction_or_ai(self):
        """The repository is a data-access layer; it must stay import-light."""
        source = __import__("pathlib").Path(
            "edu_pipeline/repository/service.py"
        ).read_text(encoding="utf-8")
        assert "topic_extractor" not in source
        assert "edu_pipeline.ai" not in source
