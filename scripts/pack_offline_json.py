#!/usr/bin/env python3
"""Embed a viewer JSON's figures so it renders with no network.

``*_questions.json`` and ``*_theory.json`` point at figures by local path and by
the original Mathpix URL. Neither survives being sent to someone else: the path
is meaningless on their machine and the URL needs the internet. This rewrites the
document with each figure's bytes inlined as base64, which the viewers already
prefer over both.

Usage::

    python scripts/pack_offline_json.py "outputs/<book>/<book>_questions.json"
    python scripts/pack_offline_json.py <file> --out ~/Desktop/book.offline.json

Pair the result with a viewer built by
``scripts/build_standalone_viewer.py --offline``.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.shared.paths import PROJECT_ROOT


def _iter_image_lists(document: Dict[str, Any]) -> Iterator[List[Dict[str, Any]]]:
    """Every ``images`` array in a questions or theory document."""
    for chapter in document.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        for key in ("questions", "sections"):
            for item in chapter.get(key) or []:
                if isinstance(item, dict) and isinstance(item.get("images"), list):
                    yield item["images"]


def _resolve(file_path: str) -> Path | None:
    """Locate a figure named by a path relative to the repo root or the CWD."""
    if not file_path:
        return None
    for candidate in (Path(file_path), PROJECT_ROOT / file_path):
        if candidate.is_file():
            return candidate
    return None


def pack(source: Path, out: Path | None = None) -> Path:
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document.get("chapters"), list):
        raise SystemExit(f"{source.name} is not a questions/theory document (no chapters[]).")

    # One cache entry per file: the same figure is referenced by many questions,
    # and embedding it once per reference would multiply the output size.
    encoded: Dict[str, Dict[str, str]] = {}
    embedded = missing = 0
    missing_examples: List[str] = []

    for images in _iter_image_lists(document):
        for image in images:
            if not isinstance(image, dict) or image.get("base64"):
                continue
            path_text = image.get("file") or ""
            if path_text not in encoded:
                resolved = _resolve(path_text)
                if resolved is None:
                    encoded[path_text] = {}
                else:
                    mime = mimetypes.guess_type(resolved.name)[0] or "image/jpeg"
                    encoded[path_text] = {
                        "base64": base64.b64encode(resolved.read_bytes()).decode("ascii"),
                        "mime_type": mime,
                    }
            payload = encoded[path_text]
            if payload:
                image.update(payload)
                embedded += 1
            else:
                missing += 1
                if len(missing_examples) < 5 and path_text:
                    missing_examples.append(path_text)

    document.setdefault("packaging", {})["figures"] = "embedded"
    target = out or source.with_suffix("").with_suffix("")
    if out is None:
        target = source.parent / (source.stem + ".offline.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    print(f"Embedded {embedded} figure reference(s) from {sum(1 for v in encoded.values() if v)} file(s).")
    if missing:
        print(f"Warning: {missing} reference(s) had no readable file and will fall back to their URL:")
        for example in missing_examples:
            print(f"    {example}")
        print("  Re-run extraction with --with-images if you need those offline.")
    print(f"Wrote {target} ({target.stat().st_size / 1048576:.1f} MB, "
          f"source was {source.stat().st_size / 1048576:.1f} MB)")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json_path", help="A *_questions.json or *_theory.json")
    parser.add_argument("--out", default=None, help="Output file (default: <name>.offline.json)")
    args = parser.parse_args(argv)

    source = Path(args.json_path).expanduser()
    if not source.is_file():
        raise SystemExit(f"No such file: {source}")
    pack(source, Path(args.out).expanduser() if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
