#!/usr/bin/env python3
"""Build a single-file, shareable copy of a Viewer page.

The served viewers pull their stylesheet and rendering library from
``Viewer/lib/``. That is right for the app but useless for sending someone a
reviewable copy: they would need all three files in the right layout *and* a
running server. This inlines the assets into one HTML file that opens by
double-clicking and asks for the JSON with a file picker.

Usage::

    python scripts/build_standalone_viewer.py                 # questions viewer
    python scripts/build_standalone_viewer.py --page theory_viewer.html
    python scripts/build_standalone_viewer.py --out ~/Desktop

    python scripts/build_standalone_viewer.py --offline        # no network at all

The result needs no server and uploads nothing -- the JSON is read in the
browser. By default MathJax is still fetched from a CDN; ``--offline`` vendors it
into the page instead, using the SVG build because it carries its own glyphs and
so needs no font downloads. Pair an ``--offline`` viewer with a JSON packed by
``scripts/pack_offline_json.py`` (figures embedded) for a copy that works with no
network whatsoever.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.shared.paths import PACKAGE_ROOT, PROJECT_ROOT

VIEWER_DIR = PACKAGE_ROOT / "web" / "frontend" / "Viewer"
DEFAULT_PAGE = "questions_viewer.html"

# The SVG build embeds its glyph outlines; the default CHTML build would still
# pull web fonts from the CDN at render time and so is not offline-capable.
MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-svg.js"
MATHJAX_TAG_RE = re.compile(
    r'[ \t]*<script id="MathJax-script"[^>]*src="[^"]+"></script>\s*\n?', re.IGNORECASE)

LINK_RE = re.compile(r'[ \t]*<link[^>]+href="\./lib/([^"]+)"[^>]*>\s*\n?', re.IGNORECASE)
SCRIPT_RE = re.compile(r'[ \t]*<script src="\./lib/([^"]+)"></script>\s*\n?', re.IGNORECASE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def vendored_mathjax() -> str:
    """MathJax source, downloaded once into .vendor/ and reused after that."""
    cache = PROJECT_ROOT / ".vendor" / "tex-mml-svg.js"
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading MathJax (once) from {MATHJAX_URL} …")
        try:
            with urllib.request.urlopen(MATHJAX_URL, timeout=120) as response:
                cache.write_bytes(response.read())
        except Exception as exc:
            raise SystemExit(
                f"Could not download MathJax for --offline ({exc}).\n"
                f"Fetch it manually to {cache} and re-run."
            )
    return cache.read_text(encoding="utf-8")


def build(page: str = DEFAULT_PAGE, out_dir: Path | None = None,
          offline: bool = False) -> Path:
    source = VIEWER_DIR / page
    if not source.is_file():
        raise SystemExit(f"No such viewer page: {source}")

    html = _read(source)
    inlined: list[str] = []

    def inline_css(match: re.Match) -> str:
        name = match.group(1)
        inlined.append(name)
        return "  <style>\n" + _read(VIEWER_DIR / "lib" / name) + "\n  </style>\n"

    def inline_js(match: re.Match) -> str:
        name = match.group(1)
        inlined.append(name)
        # No </script> can appear inside an inlined script or the parser ends the
        # block early; the library has none, but split defensively.
        body = _read(VIEWER_DIR / "lib" / name).replace("</script>", "<\\/script>")
        return "  <script>\n" + body + "\n  </script>\n"

    html = LINK_RE.sub(inline_css, html)
    html = SCRIPT_RE.sub(inline_js, html)

    if offline:
        mathjax = vendored_mathjax().replace("</script>", "<\\/script>")
        # A lambda, not a template string: the MathJax source is full of \u
        # escapes that re would otherwise try to interpret as replacements.
        block = "  <script>\n" + mathjax + "\n  </script>\n"
        html, replaced = MATHJAX_TAG_RE.subn(lambda _match: block, html)
        if not replaced:
            raise SystemExit("Could not find the MathJax <script> tag to vendor.")
        # The SVG build renders <svg>, so the CHTML-specific overflow rule the
        # shared stylesheet sets on mjx-container needs to cover it too.
        html = html.replace(
            "mjx-container{overflow-x:auto;max-width:100%}",
            "mjx-container{overflow-x:auto;max-width:100%}\n    mjx-container svg{max-width:100%}")
        inlined.append("tex-mml-svg.js")

    if not inlined:
        raise SystemExit(f"{page} references no ./lib/ assets — nothing to inline.")
    leftover = re.search(r'(?:href|src)="\./lib/', html)
    if leftover:
        raise SystemExit("An asset reference survived inlining; the page would not be standalone.")
    if offline and re.search(r'src="https?://', html):
        raise SystemExit("A remote <script> survived --offline; the page would still need the network.")

    # Cross-page links only resolve inside the served app.
    html = re.sub(r'<a href=\'\./[^\']+\'>([^<]*)</a>', r"\1", html)

    banner = (
        "<!--\n"
        "  Standalone build - no server needed.\n"
        "  Open this file in a browser and choose a <book>_questions.json (or drop\n"
        "  one onto the page). The JSON is read locally and never uploaded.\n"
        f"  Generated from {page} by scripts/build_standalone_viewer.py.\n"
        "-->\n"
    )
    html = html.replace("<!doctype html>", "<!doctype html>\n" + banner, 1)

    target_dir = out_dir or (PROJECT_ROOT / "dist")
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = page.replace(".html", "").replace("_", "-")
    suffix = "-offline" if offline else "-standalone"
    target = target_dir / f"Foundation-{stem}{suffix}.html"
    target.write_text(html, encoding="utf-8")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--page", default=DEFAULT_PAGE,
                        help=f"Viewer page to bundle (default: {DEFAULT_PAGE})")
    parser.add_argument("--out", default=None, help="Output directory (default: dist/)")
    parser.add_argument("--offline", action="store_true",
                        help="Vendor MathJax into the page so it needs no network")
    args = parser.parse_args(argv)

    target = build(args.page, Path(args.out).expanduser() if args.out else None,
                   offline=args.offline)
    size_kb = target.stat().st_size / 1024
    wanted = "*_theory.json" if "theory" in args.page else "*_questions.json"
    print(f"Wrote {target} ({size_kb:.0f} KB)")
    print(f"Share this one file; open it in a browser and pick a {wanted}.")
    if args.offline:
        print("MathJax is vendored in. For figures without a network too, pack the "
              "JSON with: python scripts/pack_offline_json.py <file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
