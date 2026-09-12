"""Image and asset processing utilities.

Handles Mathpix CDN image downloads, local caching, lossless/lossy compression,
markdown tokenization ([image:img_001]), and concept map crop adjustments.
"""

from __future__ import annotations

import base64
import io
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HTML_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
MATHPIX_URL_RE = re.compile(r"https?://[^)\s]*mathpix[^)\s]*", re.IGNORECASE)

IMAGE_COMPRESSED_MARKER = "edu-pipeline-compressed"

FOUNDATION_LOGO_MIN_X = int(os.environ.get("FOUNDATION_LOGO_MIN_X", "1300"))
FOUNDATION_LOGO_MAX_Y = int(os.environ.get("FOUNDATION_LOGO_MAX_Y", "650"))
FOUNDATION_LOGO_BAND_PX = int(os.environ.get("FOUNDATION_LOGO_BAND_PX", "460"))
MIN_CONCEPT_MAP_IMAGE_AREA = int(os.environ.get("MIN_CONCEPT_MAP_IMAGE_AREA", "120000"))
IMAGE_MAX_DIM = int(os.environ.get("IMAGE_MAX_DIM", "1000"))
IMAGE_JPEG_QUALITY = int(os.environ.get("IMAGE_JPEG_QUALITY", "78"))


def _mathpix_image_area(url: str) -> int:
    match = re.search(r"height=(\d+)&width=(\d+)", url, re.IGNORECASE)
    if match:
        return int(match.group(1)) * int(match.group(2))
    return 0


def _parse_mathpix_crop(url: str) -> Tuple[int, int, int, int]:
    """Return width, height, top_left_x, top_left_y (0 when absent)."""
    width = height = top_x = top_y = 0
    match = re.search(r"height=(\d+)&width=(\d+)", url, re.IGNORECASE)
    if match:
        height, width = int(match.group(1)), int(match.group(2))
    match = re.search(r"top_left_y=(\d+)", url, re.IGNORECASE)
    if match:
        top_y = int(match.group(1))
    match = re.search(r"top_left_x=(\d+)", url, re.IGNORECASE)
    if match:
        top_x = int(match.group(1))
    return width, height, top_x, top_y


def _is_foundation_brand_logo_url(url: str) -> bool:
    """Detect the 'Build Strong Foundation' star logo (upper-right chapter opener)."""
    width, height, top_x, top_y = _parse_mathpix_crop(url)
    if not width or not height:
        return False
    return (
        top_x >= FOUNDATION_LOGO_MIN_X
        and top_y <= FOUNDATION_LOGO_MAX_Y
        and 380 <= width <= 550
        and 380 <= height <= 550
    )


def _recrop_concept_map_excluding_logo_band(url: str) -> str:
    """Drop standalone logo crops; trim logo band from full-page concept-map crops."""
    if _is_foundation_brand_logo_url(url):
        return ""
    width, height, _top_x, top_y = _parse_mathpix_crop(url)
    if not width or not height:
        return url
    if top_y <= 500 and width >= 1200 and height >= 1200:
        new_top_y = top_y + FOUNDATION_LOGO_BAND_PX
        new_height = height - FOUNDATION_LOGO_BAND_PX
        if new_height >= 400:
            url = re.sub(
                r"top_left_y=\d+",
                f"top_left_y={new_top_y}",
                url,
                count=1,
                flags=re.IGNORECASE,
            )
            url = re.sub(
                r"height=\d+",
                f"height={new_height}",
                url,
                count=1,
                flags=re.IGNORECASE,
            )
    return url


def _prepare_concept_map_urls(urls: List[str]) -> List[str]:
    seen: Set[str] = set()
    prepared: List[str] = []
    for url in urls:
        processed = _recrop_concept_map_excluding_logo_band(url)
        if processed and processed not in seen:
            seen.add(processed)
            prepared.append(processed)
    return prepared


def _strip_foundation_logo_images_from_markdown(markdown: str) -> str:
    """Remove logo ![](...) references from concept-map markdown text."""
    if not markdown:
        return markdown
    cleaned = markdown
    for url in IMAGE_MD_RE.findall(markdown):
        if _is_foundation_brand_logo_url(url):
            cleaned = cleaned.replace(f"![]({url})", "")
    from edu_pipeline.extraction.topic_extractor import compact_markdown
    return compact_markdown(cleaned)


def _remove_concept_map_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from edu_pipeline.extraction.topic_extractor import CONCEPT_MAP_HEADING_RE, theory_section_heading
    kept: List[Dict[str, Any]] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            kept.append(sec)
            continue
        if sec.get("section_kind") == "concept_map":
            continue
        if CONCEPT_MAP_HEADING_RE.search(theory_section_heading(sec) or ""):
            continue
        kept.append(sec)
    return kept


def _is_fullpage_concept_map_url(url: str) -> bool:
    """Single full-spread concept map image (chapter 1 style)."""
    width, height, _, _ = _parse_mathpix_crop(url)
    if not width or not height:
        return False
    return (
        width >= 1200
        and height >= 1200
        and width * height >= MIN_CONCEPT_MAP_IMAGE_AREA
    )


def _mathpix_page_key(url: str) -> str:
    match = re.search(r"cropped/(.+?)(?:-\d+)?\.jpg", url, re.IGNORECASE)
    return match.group(1) if match else url


def _concept_map_body_text_only(body: str) -> str:
    text = body or ""
    text = IMAGE_MD_RE.sub("", text)
    text = re.sub(r"\[\^\d+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def compress_image_file(path: str) -> bool:
    """Downscale and re-encode a cached figure in place; True when it shrank."""
    if IMAGE_MAX_DIM <= 0 or not path or not os.path.exists(path):
        return False
    try:
        from PIL import Image, PngImagePlugin
    except ImportError:
        return False

    try:
        original_size = os.path.getsize(path)
        is_png = path.lower().endswith(".png")
        with Image.open(path) as source:
            info = source.info or {}
            stamped = info.get("Software") if is_png else info.get("comment")
            if isinstance(stamped, bytes):
                stamped = stamped.decode("utf-8", "ignore")
            if stamped == IMAGE_COMPRESSED_MARKER:
                return False

            image = source.convert("RGBA" if is_png else "RGB")
            width, height = image.size
            if max(width, height) > IMAGE_MAX_DIM:
                scale = IMAGE_MAX_DIM / float(max(width, height))
                image = image.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
            elif original_size <= 40_000:
                return False

            buffer = io.BytesIO()
            if is_png:
                meta = PngImagePlugin.PngInfo()
                meta.add_text("Software", IMAGE_COMPRESSED_MARKER)
                image.save(buffer, "PNG", optimize=True, pnginfo=meta)
            else:
                image.save(
                    buffer, "JPEG",
                    quality=IMAGE_JPEG_QUALITY, optimize=True, progressive=True,
                    comment=IMAGE_COMPRESSED_MARKER.encode("utf-8"),
                )
        if buffer.tell() >= original_size:
            return False
        with open(path, "wb") as handle:
            handle.write(buffer.getvalue())
        return True
    except Exception as exc:
        print(f"  Warning: could not compress {os.path.basename(path)}: {exc}")
        return False


def strip_images_from_markdown(md: str) -> str:
    """Remove all markdown/HTML images (standalone lines, table cells, headings)."""
    from edu_pipeline.extraction.topic_extractor import compact_markdown
    lines: List[str] = []
    for raw_line in md.splitlines():
        line = HTML_IMG_RE.sub("", raw_line)
        line = MARKDOWN_IMAGE_RE.sub("", line)
        line = BR_TAG_RE.sub(" ", line)
        line = re.sub(r"[ \t]{2,}", " ", line).rstrip()
        if not line.strip():
            continue
        lines.append(line)

    out: List[str] = []
    prev_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank
    return compact_markdown("\n".join(out))


def strip_markdown_images(text: str) -> str:
    """Remove images from JSON text fields when SKIP_IMAGES is enabled."""
    from edu_pipeline.extraction.topic_extractor import skip_images
    if not text or not skip_images():
        return text or ""
    return strip_images_from_markdown(text)


class ImageResolver:
    def __init__(self, book_name: str, topic_number: Optional[int] = None):
        from edu_pipeline.shared.paths import OUTPUT_DIR
        image_cache_dir = os.path.join(OUTPUT_DIR, "image_cache")
        self.book_name = book_name
        self.topic_number = topic_number
        base = os.path.join(image_cache_dir, book_name)
        if topic_number is not None:
            base = os.path.join(base, f"topic_{int(topic_number):02d}")
        self.cache_dir = base
        self.url_to_id: Dict[str, str] = {}
        self.assets: Dict[str, Dict[str, str]] = {}
        self._counter = 0
        os.makedirs(self.cache_dir, exist_ok=True)

    def register_markdown(self, markdown: str) -> None:
        for url in IMAGE_MD_RE.findall(markdown):
            if url not in self.url_to_id:
                self._counter += 1
                img_id = f"img_{self._counter:03d}"
                self.url_to_id[url] = img_id
                ext = ".jpg"
                if ".png" in url.lower():
                    ext = ".png"
                local_path = os.path.join(self.cache_dir, f"{img_id}{ext}")
                self.assets[img_id] = {
                    "source_url": url,
                    "file": local_path.replace("\\", "/"),
                }

    def _mathpix_headers(self) -> Dict[str, str]:
        from edu_pipeline.extraction.topic_extractor import MATHPIX_APP_ID, MATHPIX_APP_KEY
        headers: Dict[str, str] = {}
        if MATHPIX_APP_ID and MATHPIX_APP_KEY:
            headers["app_id"] = MATHPIX_APP_ID
            headers["app_key"] = MATHPIX_APP_KEY
        return headers

    def _ensure_downloaded(self, url: str, local_path: str) -> None:
        if os.path.exists(local_path):
            compress_image_file(local_path)
            return
        try:
            resp = requests.get(
                url,
                headers=self._mathpix_headers(),
                timeout=60,
            )
            if resp.ok:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                compress_image_file(local_path)
                return
            print(f"Warning: download HTTP {resp.status_code} for {url[:80]}...")
        except Exception as exc:
            print(f"Warning: failed to download {url}: {exc}")

    def replace_urls_with_ids(self, text: str) -> str:
        def repl(match: re.Match) -> str:
            url = match.group(1)
            img_id = self.url_to_id.get(url, "")
            return f"[image:{img_id}]" if img_id else match.group(0)
        return IMAGE_MD_RE.sub(repl, text)

    def collect_referenced_ids(self, obj: Any) -> Set[str]:
        found: Set[str] = set()
        if isinstance(obj, str):
            found.update(re.findall(r"\[image:(img_\d+)\]", obj))
            for url, img_id in self.url_to_id.items():
                if url in obj:
                    found.add(img_id)
        elif isinstance(obj, dict):
            for v in obj.values():
                found.update(self.collect_referenced_ids(v))
        elif isinstance(obj, list):
            for v in obj:
                found.update(self.collect_referenced_ids(v))
        return found

    def build_image_list(self, referenced_ids: Set[str]) -> List[Dict[str, str]]:
        from edu_pipeline.extraction.topic_extractor import skip_images
        if skip_images():
            return []
        images: List[Dict[str, str]] = []
        for img_id in sorted(referenced_ids):
            asset = self.assets.get(img_id)
            if not asset:
                continue
            local_path = asset["file"]
            if not os.path.exists(local_path):
                self._ensure_downloaded(asset["source_url"], local_path)
            if not os.path.exists(local_path):
                continue
            compress_image_file(local_path)
            with open(local_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            mime = "image/png" if local_path.endswith(".png") else "image/jpeg"
            images.append({
                "id": img_id,
                "caption": "",
                "base64": data,
                "mime_type": mime,
            })
        return images

    def get_assets_dict(self) -> Dict[str, Dict[str, str]]:
        return dict(self.assets)


def embed_base64_in_assets(resolver: ImageResolver) -> Dict[str, Dict[str, str]]:
    """Embed base64 image data in all registered assets for the final JSON."""
    from edu_pipeline.extraction.topic_extractor import skip_images
    if skip_images():
        return {}
    assets_out: Dict[str, Dict[str, str]] = {}
    for img_id, asset in resolver.assets.items():
        entry = dict(asset)
        local_path = entry.get("file", "")
        if local_path and not os.path.isabs(local_path):
            local_path = os.path.normpath(local_path)
        if local_path and os.path.exists(local_path):
            compress_image_file(local_path)
            with open(local_path, "rb") as handle:
                entry["base64"] = base64.b64encode(handle.read()).decode("ascii")
            entry["mime_type"] = (
                "image/png" if local_path.lower().endswith(".png") else "image/jpeg"
            )
        elif entry.get("source_url"):
            resolver._ensure_downloaded(entry["source_url"], local_path)
            if local_path and os.path.exists(local_path):
                with open(local_path, "rb") as handle:
                    entry["base64"] = base64.b64encode(handle.read()).decode("ascii")
                entry["mime_type"] = (
                    "image/png" if local_path.lower().endswith(".png") else "image/jpeg"
                )
        assets_out[img_id] = entry
    return assets_out
