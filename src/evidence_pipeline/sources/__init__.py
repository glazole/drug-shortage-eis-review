"""Bibliographic source adapters."""

from .base import SourceAdapter
from .registry import build_source_registry

__all__ = ["SourceAdapter", "build_source_registry"]
