"""
Response parser for OmniCortex rich media tags.

Supported tags:
- [image][filename.ext]
- [video][filename.ext]
- [document][filename.ext]
- [location][lat,long][name][address]
- [buttons][Title][Option1|Option2]
- [link][url][text]
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from .agent_manager import get_agent

IMAGE_RE = re.compile(r"\[image\]\[(.*?)\]", re.IGNORECASE)
VIDEO_RE = re.compile(r"\[video\]\[(.*?)\]", re.IGNORECASE)
DOC_RE = re.compile(r"\[document\]\[(.*?)\]", re.IGNORECASE)
LINK_RE = re.compile(r"\[link\]\[(.*?)\]\[(.*?)\]", re.IGNORECASE)
LOC_RE = re.compile(r"\[location\]\[(.*?)\]\[(.*?)\]\[(.*?)\]", re.IGNORECASE)
BTN_RE = re.compile(r"\[buttons\]\[(.*?)\]\[(.*?)\]", re.IGNORECASE)


def parse_response(answer: str, agent_id: str = None) -> List[Dict[str, Any]]:
    """Parse tagged LLM output into ordered structured parts."""
    if not answer:
        return [{"type": "text", "content": ""}]

    agent = get_agent(agent_id) if agent_id else None
    parts: List[Dict[str, Any]] = []

    cursor = 0
    length = len(answer)

    while cursor < length:
        matches = []
        for tag_type, regex in (
            ("image", IMAGE_RE),
            ("video", VIDEO_RE),
            ("document", DOC_RE),
            ("link", LINK_RE),
            ("location", LOC_RE),
            ("buttons", BTN_RE),
        ):
            m = regex.search(answer, cursor)
            if m:
                matches.append((m.start(), m, tag_type))

        if not matches:
            tail = answer[cursor:].strip()
            if tail:
                parts.append({"type": "text", "content": tail})
            break

        matches.sort(key=lambda x: x[0])
        start, match, tag_type = matches[0]

        if start > cursor:
            text_before = answer[cursor:start].strip()
            if text_before:
                parts.append({"type": "text", "content": text_before})

        if tag_type == "image":
            filename = match.group(1).strip()
            url = _resolve_media_url(filename, agent, "image")
            if url:
                parts.append({"type": "image", "url": url, "caption": filename})
            else:
                parts.append({"type": "text", "content": f"(Image not found: {filename})"})

        elif tag_type == "video":
            filename = match.group(1).strip()
            url = _resolve_media_url(filename, agent, "video")
            if url:
                parts.append({"type": "video", "url": url, "caption": filename})
            else:
                parts.append({"type": "text", "content": f"(Video not found: {filename})"})

        elif tag_type == "document":
            filename = match.group(1).strip()
            url = _resolve_document_url(filename, agent_id)
            if url:
                parts.append(
                    {
                        "type": "document",
                        "url": url,
                        "caption": filename,
                        "filename": filename,
                    }
                )
            else:
                parts.append({"type": "text", "content": f"(Document not found: {filename})"})

        elif tag_type == "link":
            url = match.group(1).strip()
            text = match.group(2).strip()
            parts.append({"type": "text", "content": f"{text}: {url}", "preview_url": url})

        elif tag_type == "location":
            latlong = match.group(1).strip()
            name = match.group(2).strip()
            address = match.group(3).strip()
            try:
                lat_str, lng_str = [x.strip() for x in latlong.split(",", 1)]
                parts.append(
                    {
                        "type": "location",
                        "latitude": float(lat_str),
                        "longitude": float(lng_str),
                        "name": name,
                        "address": address,
                    }
                )
            except ValueError:
                parts.append({"type": "text", "content": f"Location: {name}, {address} ({latlong})"})

        elif tag_type == "buttons":
            title = match.group(1).strip()
            options = [opt.strip() for opt in match.group(2).split("|") if opt.strip()]
            parts.append(
                {
                    "type": "interactive",
                    "interaction_type": "button",
                    "body": title,
                    "buttons": [
                        {"id": f"btn_{i + 1}", "title": opt[:20]}
                        for i, opt in enumerate(options[:3])
                    ],
                }
            )

        cursor = match.end()

    if not parts:
        return [{"type": "text", "content": ""}]

    return parts


def process_rich_response_for_frontend(answer: str, agent_id: str = None) -> str:
    """Convert tags into web-friendly markdown-like output."""
    if not answer:
        return ""

    agent = get_agent(agent_id) if agent_id else None
    processed = answer

    def image_sub(match: re.Match[str]) -> str:
        filename = match.group(1).strip()
        url = _resolve_media_url(filename, agent, "image")
        return f"![{filename}]({url})" if url else f"(Image: {filename} not found)"

    def video_sub(match: re.Match[str]) -> str:
        filename = match.group(1).strip()
        url = _resolve_media_url(filename, agent, "video")
        return f"[Video: {filename}]({url})" if url else f"(Video: {filename} not found)"

    def document_sub(match: re.Match[str]) -> str:
        filename = match.group(1).strip()
        url = _resolve_document_url(filename, agent_id)
        return f"[Download {filename}]({url})" if url else f"(Document: {filename} not found)"

    def location_sub(match: re.Match[str]) -> str:
        latlong = match.group(1).strip()
        name = match.group(2).strip()
        address = match.group(3).strip()
        return f"📍 Location: {name}, {address} ({latlong})"

    def buttons_sub(match: re.Match[str]) -> str:
        title = match.group(1).strip()
        options = match.group(2).strip()
        return f"**{title}**\nOptions: {options}"

    processed = IMAGE_RE.sub(image_sub, processed)
    processed = VIDEO_RE.sub(video_sub, processed)
    processed = DOC_RE.sub(document_sub, processed)
    processed = LINK_RE.sub(r"[\2](\1)", processed)
    processed = LOC_RE.sub(location_sub, processed)
    processed = BTN_RE.sub(buttons_sub, processed)

    return processed


# Backward-compatible alias used by api.py
replace_image_tags_with_urls = process_rich_response_for_frontend


def _resolve_media_url(filename: str, agent: Optional[Dict[str, Any]], media_type: str) -> Optional[str]:
    if not filename:
        return None
    if filename.startswith(("http://", "https://")):
        return filename
    if not agent:
        return None

    urls = agent.get("image_urls") or [] if media_type == "image" else agent.get("video_urls") or []
    if not urls:
        return None

    q_raw = _normalize_text(filename, keep_ext=True)
    q_file = _extract_filename(filename, keep_ext=True)
    q_stem = _extract_filename(filename, keep_ext=False)
    q_slug = _slugify(q_stem or q_file or q_raw)

    best_url: Optional[str] = None
    best_score = -1

    for entry in urls:
        media_url = _extract_url_from_entry(entry)
        if not media_url:
            continue

        c_raw = _normalize_text(media_url, keep_ext=True)
        c_file = _extract_filename(media_url, keep_ext=True)
        c_stem = _extract_filename(media_url, keep_ext=False)
        c_slug = _slugify(c_stem or c_file or c_raw)

        score = 0

        # Exact matches
        if q_file and c_file and q_file == c_file:
            score = 100
        elif q_stem and c_stem and q_stem == c_stem:
            score = 98
        elif q_slug and c_slug and q_slug == c_slug:
            score = 96
        # Containment
        elif q_file and c_file and (q_file in c_file or c_file in q_file):
            score = 90
        elif q_stem and c_stem and (q_stem in c_stem or c_stem in q_stem):
            score = 85
        elif q_slug and c_slug and (q_slug in c_slug or c_slug in q_slug):
            score = 80
        # Token overlap for near matches
        else:
            q_tokens = set(q_slug.split()) if q_slug else set()
            c_tokens = set(c_slug.split()) if c_slug else set()
            overlap = len(q_tokens & c_tokens)
            if overlap >= 2:
                score = 70 + overlap
            elif overlap == 1:
                score = 60

        if score > best_score:
            best_score = score
            best_url = media_url

        if score >= 98:
            return media_url

    # Avoid very weak random matches.
    if best_score >= 70:
        return best_url

    return None


def _extract_url_from_entry(entry: Any) -> Optional[str]:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("url", "link", "src", "path"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _normalize_text(value: str, keep_ext: bool = True) -> str:
    text = unquote(str(value or "")).strip().lower()
    if not keep_ext:
        text = _extract_filename(text, keep_ext=False)
    return text


def _extract_filename(value: str, keep_ext: bool = True) -> str:
    text = unquote(str(value or "")).strip().replace("\\", "/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    text = text.split("?", 1)[0]
    if not keep_ext and "." in text:
        text = text.rsplit(".", 1)[0]
    return text.lower().strip()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _resolve_document_url(filename: str, agent_id: str) -> Optional[str]:
    if not filename:
        return None
    if filename.startswith(("http://", "https://")):
        return filename
    if not agent_id:
        return None

    try:
        from .database import Document, SessionLocal

        db = SessionLocal()
        try:
            doc = (
                db.query(Document)
                .filter(Document.agent_id == agent_id, Document.filename.ilike(f"%{filename}%"))
                .first()
            )
            if not doc:
                return None

            extra = doc.extra_data or {}
            source_url = extra.get("url") or extra.get("source_url")
            if source_url and str(source_url).startswith(("http://", "https://")):
                return str(source_url)

            # Fallback to an existing endpoint that at least exposes document content/chunks.
            return f"/documents/{doc.id}/chunks"
        finally:
            db.close()
    except Exception:
        return None
