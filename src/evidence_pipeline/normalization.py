"""Deterministic identifier and title normalization."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata


DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = DOI_PREFIX_RE.sub("", value.strip()).strip().lower()
    return normalized or None


def clean_markup(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = html.unescape(HTML_TAG_RE.sub(" ", value))
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned or None


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = NON_WORD_RE.sub(" ", normalized)
    return SPACE_RE.sub(" ", normalized).strip()


def candidate_work_id(title: str, year: int | None, doi: str | None) -> str:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    basis = f"{normalize_title(title)}|{year or ''}".encode("utf-8")
    return f"title-year:{hashlib.sha256(basis).hexdigest()[:24]}"
