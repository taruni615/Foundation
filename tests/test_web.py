"""Web smoke tests: both servers must start and serve their core routes.

These launch the real entry points as subprocesses, so they cover the wiring a
unit test cannot: import order, .env loading, static asset resolution and route
dispatch. Routes needing MySQL are marked and skipped by default.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

BOOK = urllib.parse.quote("10 PHYSICS FOUNDATION")


class TestAppServer:
    def test_serves_the_single_page_app(self, app_server):
        status, body = app_server.get("/")
        assert status == 200
        assert b"<html" in body.lower() or b"<!doctype" in body.lower()

    def test_attributes_endpoint_returns_the_selector_vocabulary(self, app_server):
        status, body = app_server.get("/api/attributes")
        assert status == 200
        payload = json.loads(body)
        assert "subjects" in payload or "boards" in payload or "classes" in payload

    def test_mcq_health_reports_without_crashing_when_ollama_is_absent(self, app_server):
        """Degrade gracefully: report status, never 500."""
        status, body = app_server.get("/api/mcq/health")
        assert status == 200
        assert "ollama_ok" in json.loads(body)

    def test_extraction_requires_a_book_parameter(self, app_server):
        status, body = app_server.get("/api/extraction")
        assert status == 404
        assert "error" in json.loads(body)

    def test_unknown_api_route_returns_json_not_html(self, app_server):
        status, body = app_server.get("/api/definitely-not-a-route")
        assert status in (404, 400)
        assert body.strip().startswith(b"{")

    def test_static_traversal_is_rejected(self, app_server):
        status, _ = app_server.get("/../../etc/passwd")
        assert status in (403, 404)

    def test_protected_route_requires_authentication(self, app_server):
        status, _ = app_server.get("/api/auth/me")
        assert status == 401

    def test_study_notes_returns_json_for_a_known_book(self, app_server):
        status, body = app_server.get(f"/api/study-notes?book={BOOK}")
        assert status == 200
        assert isinstance(json.loads(body), dict)


class TestViewerApi:
    def test_root_serves_the_textbook_viewer(self, viewer_server):
        status, body = viewer_server.get("/")
        assert status == 200
        assert b"<html" in body.lower() or b"<!doctype" in body.lower()

    @pytest.mark.parametrize("path", [
        "/Viewer/textbook_viewer.html",
        "/Viewer/output_json_viewer.html",
    ])
    def test_serves_the_bundled_viewer_pages(self, viewer_server, path):
        """Regression: these 404'd after the package refactor moved Viewer/."""
        status, body = viewer_server.get(path)
        assert status == 200
        assert len(body) > 1000

    def test_serves_workspace_json_for_the_json_viewer(self, viewer_server):
        status, _ = viewer_server.get(
            f"/edu_pipeline/workspace/{BOOK}/{BOOK}_final.json"
        )
        assert status in (200, 404)  # 404 only when the book has not been extracted

    def test_traversal_is_rejected(self, viewer_server):
        status, _ = viewer_server.get("/../../etc/passwd")
        assert status in (403, 404)


@pytest.mark.requires_db
class TestBankRoutes:
    """Question-bank routes need a reachable MySQL instance."""

    def test_bank_health(self, app_server):
        status, body = app_server.get("/api/bank/health")
        assert status == 200
        assert "ok" in json.loads(body) or "db_ok" in json.loads(body)

    def test_bank_items_are_paginated(self, app_server):
        status, body = app_server.get("/api/bank/items?page=1&pageSize=5")
        assert status == 200
        payload = json.loads(body)
        assert len(payload.get("items", [])) <= 5
