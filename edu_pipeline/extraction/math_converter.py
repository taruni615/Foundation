"""Mathematical and LaTeX conversion utilities (LaTeX to MathML and plain text).

Handles idempotent LaTeX-to-MathML conversion, alignment marker stripping,
MathML masking, XML sanitization, and plain text fallbacks.
"""

from __future__ import annotations

import html
import re
from typing import Any, List, Optional
from xml.etree import ElementTree as ET

try:
    import latex2mathml.converter as latex2mathml_converter
except ImportError:
    latex2mathml_converter = None


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
LATEX_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)
LATEX_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
LATEX_LEAK_RE = re.compile(r"\$[^$]+\$|\$\$[^$]+\$\$")

ALIGNMENT_ENV_RE = re.compile(
    r"(\\begin\{(aligned|align\*?|alignat\*?|flalign\*?)\})(.*?)(\\end\{\2\})",
    re.DOTALL,
)
BARE_AMPERSAND_RE = re.compile(r"(?<!\\)&(?![a-zA-Z#])")
STRAY_AMPERSAND_NODE_RE = re.compile(r"<mi>\s*&(?:amp;)?\s*</mi>")
MATHML_BLOCK_RE = re.compile(r"<math\b[\s\S]*?</math>", re.IGNORECASE)
TRIPLE_DOLLAR_RE = re.compile(r"(?<!\$)\$\$\$(?!\$)")

_SUPERSCRIPT_CHARS = str.maketrans({
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "−": "⁻", "=": "⁼",
    "(": "⁽", ")": "⁾", "n": "ⁿ", "i": "ⁱ",
})
_MO_TRIM_RE = re.compile(r"^[\s\u00A0]+|[\s\u00A0]+$")
_NO_SPACE_BEFORE = set(".,;:!?)]}°′″")
_NO_SPACE_AFTER = set("([{")


def normalize_math_delimiters(text: str) -> str:
    """Separate an inline close that abuts a block open."""
    return TRIPLE_DOLLAR_RE.sub("$\n$$", text)


def strip_alignment_markers(latex: str) -> str:
    """Drop the column separators from alignment environments."""
    def fix(match: re.Match) -> str:
        body = BARE_AMPERSAND_RE.sub(" ", match.group(3))
        return match.group(1) + body + match.group(4)

    return ALIGNMENT_ENV_RE.sub(fix, latex)


class MathConverter:
    """Idempotent LaTeX to MathML converter with XML and alignment sanitization."""

    def __init__(self):
        self._warned = False

    def latex_to_mathml(self, latex: str) -> str:
        latex = strip_alignment_markers(latex.strip())
        if not latex:
            return ""
        if latex2mathml_converter is None:
            if not self._warned:
                print("Warning: latex2mathml not installed; wrapping LaTeX in mtext.")
                self._warned = True
            escaped = latex.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<math xmlns='http://www.w3.org/1998/Math/MathML'><mtext>{escaped}</mtext></math>"
        try:
            return self._sanitize(latex2mathml_converter.convert(latex))
        except Exception:
            escaped = latex.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<math xmlns='http://www.w3.org/1998/Math/MathML'><mtext>{escaped}</mtext></math>"

    @staticmethod
    def _sanitize(mathml: str) -> str:
        cleaned = STRAY_AMPERSAND_NODE_RE.sub("", mathml)
        return BARE_AMPERSAND_RE.sub("&amp;", cleaned)

    def convert_text(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        preserved: List[str] = []

        def stash(match: re.Match) -> str:
            preserved.append(match.group(0))
            return f"\x00MATH{len(preserved) - 1}\x00"

        def convert(match: re.Match) -> str:
            return self.latex_to_mathml(match.group(1))

        masked = MATHML_BLOCK_RE.sub(stash, text)
        masked = normalize_math_delimiters(masked)

        after_block = MATHML_BLOCK_RE.sub(stash, LATEX_BLOCK_RE.sub(convert, masked))
        result = LATEX_INLINE_RE.sub(convert, after_block)

        for index, original in enumerate(preserved):
            result = result.replace(f"\x00MATH{index}\x00", original)
        return result

    def convert_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.convert_text(value)
        if isinstance(value, list):
            return [self.convert_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.convert_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def scan_latex_leaks(obj: Any, path: str = "") -> List[str]:
        leaks: List[str] = []
        if isinstance(obj, str) and LATEX_LEAK_RE.search(obj):
            leaks.append(path or "root")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                leaks.extend(MathConverter.scan_latex_leaks(v, f"{path}.{k}" if path else k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                leaks.extend(MathConverter.scan_latex_leaks(v, f"{path}[{i}]"))
        return leaks


def apply_mathml_conversion(data: Any, math: Optional[MathConverter] = None) -> Any:
    """Convert $...$ and $$...$$ LaTeX to MathML in all string fields (recursive)."""
    from edu_pipeline.extraction.topic_extractor import skip_mathml
    if skip_mathml():
        return data
    converter = math or MathConverter()
    return converter.convert_value(data)


def _mathml_local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag.lstrip("/")


def _format_superscript(exp: str) -> str:
    exp = re.sub(r"\s+", "", exp.strip())
    if not exp:
        return ""
    if exp in ("circ", "°", "∘") or "°" in exp:
        return "°"
    return exp.translate(_SUPERSCRIPT_CHARS)


def _latex_to_readable_plain(latex: str) -> str:
    s = str(latex or "").strip()
    if not s:
        return ""
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\\frac\{([^{}]+)\}", r"(\1)", s)

    def _sup_repl(match: re.Match) -> str:
        return _format_superscript(match.group(1))

    s = re.sub(r"\^\{([^{}]+)\}", _sup_repl, s)
    s = re.sub(r"_\{([^{}]+)\}", r"_\1", s)
    for pat, repl in (
        (r"\\circ", "°"), (r"\\theta", "θ"), (r"\\alpha", "α"), (r"\\beta", "β"),
        (r"\\pi", "π"), (r"\\mu", "μ"), (r"\\times", "×"), (r"\\cdot", "·"),
        (r"\\leq", "≤"), (r"\\geq", "≥"), (r"\\neq", "≠"), (r"\\infty", "∞"),
        (r"\\rightarrow", "→"), (r"\\leftarrow", "←"), (r"\\Rightarrow", "⇒"),
        (r"\\quad", " "),
    ):
        s = re.sub(pat, repl, s)
    s = s.replace(r"\left(", "(").replace(r"\right)", ")")
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _mathml_leaf_text(elem: ET.Element) -> str:
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_mathml_element_to_plain(child))
        if child.tail:
            parts.append(child.tail)
    return html.unescape("".join(parts)).strip()


def _mathml_join_parts(parts: List[str]) -> str:
    out: List[str] = []
    for part in parts:
        piece = re.sub(r"\s+", " ", str(part or "").strip())
        if not piece:
            continue
        if out:
            prev = out[-1]
            if (
                piece[0] not in _NO_SPACE_BEFORE
                and prev[-1] not in _NO_SPACE_AFTER
                and not (prev[-1].isalnum() and piece[0] in "=<>±∓∴∵")
            ):
                out.append(" ")
        out.append(piece)
    return "".join(out)


def _mathml_element_to_plain(elem: ET.Element) -> str:
    tag = _mathml_local_tag(elem.tag)
    if tag in ("math", "mrow", "mstyle", "mpadded", "mphantom", "semantics"):
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
    if tag in ("mn", "mi", "mtext", "ms"):
        return _mathml_leaf_text(elem)
    if tag == "mo":
        sym = _MO_TRIM_RE.sub("", _mathml_leaf_text(elem))
        if sym in ("", "\u200B"):
            return ""
        if sym in ("⁡",):
            return ""
        return sym
    if tag == "mspace":
        return " "
    if tag == "mfrac":
        kids = list(elem)
        if len(kids) >= 2:
            num = _mathml_element_to_plain(kids[0])
            den = _mathml_element_to_plain(kids[1])
            if re.fullmatch(r"[\w\d.]+", num) and re.fullmatch(r"[\w\d.]+", den):
                return f"{num}/{den}"
            return f"({num})/({den})"
        return _mathml_element_to_plain(kids[0]) if kids else ""
    if tag == "msup":
        kids = list(elem)
        if len(kids) >= 2:
            base = _mathml_element_to_plain(kids[0])
            exp = _mathml_element_to_plain(kids[1])
            return base + _format_superscript(exp)
        return _mathml_element_to_plain(kids[0]) if kids else ""
    if tag == "msub":
        kids = list(elem)
        if len(kids) >= 2:
            return _mathml_element_to_plain(kids[0]) + _mathml_element_to_plain(kids[1])
        return _mathml_element_to_plain(kids[0]) if kids else ""
    if tag == "msubsup":
        kids = list(elem)
        if len(kids) >= 3:
            base = _mathml_element_to_plain(kids[0])
            sub = _mathml_element_to_plain(kids[1])
            sup = _format_superscript(_mathml_element_to_plain(kids[2]))
            return f"{base}_{sub}{sup}"
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in kids])
    if tag == "msqrt":
        inner = _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
        return f"√({inner})" if inner else "√"
    if tag == "mroot":
        kids = list(elem)
        if len(kids) >= 2:
            rad = _mathml_element_to_plain(kids[0])
            idx = _mathml_element_to_plain(kids[1])
            return f"{rad}^(1/{idx})"
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in kids])
    if tag in ("mover", "munder", "munderover", "mtable", "mtr", "mtd"):
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
    if tag == "mfenced":
        open_ch = elem.get("open") or "("
        close_ch = elem.get("close") or ")"
        inner = _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
        return f"{open_ch}{inner}{close_ch}"
    return _mathml_leaf_text(elem)


def _sanitize_mathml_for_xml(block: str) -> str:
    return re.sub(
        r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)",
        "&amp;",
        block,
    )


def mathml_block_to_plain(block: str) -> str:
    raw = str(block or "").strip()
    if not raw:
        return ""
    try:
        root = ET.fromstring(_sanitize_mathml_for_xml(raw))
    except ET.ParseError:
        return _mathml_block_to_plain_fallback(raw)
    plain = _mathml_element_to_plain(root).strip()
    return plain


def _mathml_block_to_plain_fallback(block: str) -> str:
    text = re.sub(r"<mspace[^>]*/?>", " ", block, flags=re.IGNORECASE)
    text = re.sub(r"<mtext[^>]*>([\s\S]*?)</mtext>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<mn[^>]*>([\s\S]*?)</mn>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<mi[^>]*>([\s\S]*?)</mi>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<mo[^>]*>([\s\S]*?)</mo>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def replace_mathml_with_plain_text(text: str) -> str:
    if not text or not isinstance(text, str) or "<math" not in text.lower():
        return text

    def _repl(match: re.Match) -> str:
        return mathml_block_to_plain(match.group(0))

    out = MATHML_BLOCK_RE.sub(_repl, text)
    if "$" in out:
        out = LATEX_BLOCK_RE.sub(
            lambda m: _latex_to_readable_plain(m.group(1)), out,
        )
        out = LATEX_INLINE_RE.sub(
            lambda m: _latex_to_readable_plain(m.group(1)), out,
        )
    return out


def apply_math_plain_conversion(data: Any) -> Any:
    if isinstance(data, str):
        return replace_mathml_with_plain_text(data)
    if isinstance(data, list):
        return [apply_math_plain_conversion(item) for item in data]
    if isinstance(data, dict):
        return {k: apply_math_plain_conversion(v) for k, v in data.items()}
    return data
