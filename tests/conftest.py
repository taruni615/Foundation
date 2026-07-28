"""Shared fixtures.

Design rules for this suite:
  * No test may require MySQL or Ollama. Anything that would is marked
    ``requires_db`` / ``requires_ollama`` and skipped by default.
  * Tests assert on observable behaviour (returned documents, HTTP status,
    file contents), not on internal call sequences.
  * Nothing writes inside the repository; workspace fixtures use tmp_path.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Sample content
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_document() -> dict:
    """A minimal but structurally faithful v3.1 *_final.json document."""
    return {
        "metadata": {"name": "10 TEST FOUNDATION", "format_version": "3.1"},
        "topics": [
            {
                "topic_number": 1,
                "chapter_name": "Reflection of Light",
                "theory_sections": [
                    {"heading": "Laws of Reflection", "excerpt": "The angle of incidence equals the angle of reflection."},
                    {"heading": "Mirror Formula", "excerpt": "1/v + 1/u = 1/f"},
                ],
                "illustrations": [
                    {"question": "State the laws of reflection.", "answer": "Angle i = angle r.",
                     "question_type": "Short Answer"},
                ],
                "textbook_exercises": [
                    {"question": "Calculate the focal length when v=10cm and u=20cm.",
                     "answer": "f = 6.67 cm", "question_type": "Numerical"},
                ],
            },
            {
                "topic_number": 2,
                "chapter_name": "Refraction",
                "theory_sections": [{
                    "heading": "Snell's Law",
                    "excerpt": "Refraction is the bending of light as it passes between media. "
                               "Snell's law states n1 sin(i) = n2 sin(r), where n is the "
                               "refractive index of each medium.",
                }],
                "exercises": [
                    {"question": "Define refractive index.", "answer": "Ratio of speeds.",
                     "question_type": "Short Answer"},
                ],
            },
        ],
    }


@pytest.fixture
def workspace(tmp_path: Path, sample_document: dict) -> Path:
    """A temporary workspace laid out like edu_pipeline/workspace/."""
    slug = "10 TEST FOUNDATION"
    book_dir = tmp_path / slug
    book_dir.mkdir(parents=True)
    (book_dir / f"{slug}_final.json").write_text(
        json.dumps(sample_document, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def analysis_payload() -> dict:
    """A Stage 1 content-analysis payload as the notes prompt defines it."""
    return {
        "topic": "Reflection of Light",
        "definitions": ["Reflection: light bouncing off a surface"],
        "core_concepts": ["Laws of reflection", "Image formation"],
        "formulae": ["1/v + 1/u = 1/f"],
        "variables": ["v: image distance", "u: object distance", "f: focal length"],
        "derivations": ["Mirror formula derivation"],
        "common_mistakes": ["Sign convention errors"],
        "exam_points": ["Mirror formula is frequently examined"],
        "memory_candidates": ["UVF triangle"],
        "prerequisites": ["Rectilinear propagation of light"],
    }


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------
class FakeLLM:
    """Records calls and returns canned responses, so pipeline shape can be
    asserted without a model. Mirrors OllamaLLMProvider.generate's contract."""

    def __init__(self, json_reply: dict | None = None, text_reply: str = "# Notes\n\nBody.",
                 fail_models: tuple[str, ...] = (), empty_models: tuple[str, ...] = ()):
        self.calls: list[dict] = []
        self.json_reply = json_reply or {}
        self.text_reply = text_reply
        self.fail_models = fail_models
        self.empty_models = empty_models

    def install(self, monkeypatch):
        from edu_pipeline.ai.providers import llm as llm_mod
        from edu_pipeline.ai.response import LLMResponse

        fake = self

        def generate(self, system_prompt, user_prompt, temperature=0.4,
                     max_tokens=None, json_format=False):
            fake.calls.append({
                "model": self._model, "json_format": json_format,
                "temperature": temperature, "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            })
            if self._model in fake.fail_models:
                raise RuntimeError(f"simulated provider failure for {self._model}")
            if self._model in fake.empty_models:
                return LLMResponse(text="", model=self._model)
            text = json.dumps(fake.json_reply) if json_format else fake.text_reply
            return LLMResponse(text=text, model=self._model)

        monkeypatch.setattr(llm_mod.OllamaLLMProvider, "generate", generate)
        return self

    @property
    def models_used(self) -> list[str]:
        return [c["model"] for c in self.calls]


@pytest.fixture
def fake_llm(monkeypatch):
    def _make(**kwargs):
        return FakeLLM(**kwargs).install(monkeypatch)
    return _make


# ---------------------------------------------------------------------------
# Live server helper (smoke tests)
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerProcess:
    def __init__(self, script: str, port_env: str):
        self.port = _free_port()
        env = dict(os.environ, **{port_env: str(self.port)})
        self.proc = subprocess.Popen(
            [sys.executable, script], cwd=str(PROJECT_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self._wait_ready()

    def _wait_ready(self, timeout: float = 25.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early:\n{self.proc.stdout.read()}")
            try:
                self.get("/")
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("server did not become ready in time")

    def get(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture(scope="module")
def app_server():
    srv = ServerProcess("scripts/app_server.py", "APP_PORT")
    yield srv
    srv.close()


@pytest.fixture(scope="module")
def viewer_server():
    srv = ServerProcess("scripts/viewer_api.py", "VIEWER_API_PORT")
    yield srv
    srv.close()
