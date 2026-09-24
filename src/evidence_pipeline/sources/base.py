"""Base class and resilient HTTP behaviour for source adapters."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable

from ..config import SourceConfig
from ..exceptions import (
    HttpStatusError,
    SourceRequestError,
    SourceUnavailableError,
    TransportError,
    UnsupportedCapabilityError,
)
from ..http import HttpClient, UrllibHttpClient
from ..models import WorkRecord


class SourceAdapter(ABC):
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        config: SourceConfig,
        *,
        contact_email: str,
        http_client: HttpClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.contact_email = contact_email
        self.http = http_client or UrllibHttpClient()
        self.sleep = sleep

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": f"drug-shortage-eis-review/0.1 (mailto:{self.contact_email})",
        }

    def _with_retries(self, operation: Callable[[], Any]) -> Any:
        attempts = max(1, self.config.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return operation()
            except HttpStatusError as exc:
                if exc.status_code not in self.transient_statuses:
                    raise SourceRequestError(str(exc)) from exc
                last_error = exc
            except TransportError as exc:
                last_error = exc
            if attempt < attempts - 1:
                self.sleep(self.config.backoff_seconds * (2**attempt))
        raise SourceUnavailableError(
            f"{self.name} unavailable after {attempts} attempts: {last_error}"
        ) from last_error

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged_headers = self.default_headers | (headers or {})
        return self._with_retries(
            lambda: self.http.get_json(
                url,
                params=params,
                headers=merged_headers,
                timeout=self.config.timeout_seconds,
            )
        )

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        merged_headers = self.default_headers | (headers or {})
        return self._with_retries(
            lambda: self.http.get_text(
                url,
                params=params,
                headers=merged_headers,
                timeout=self.config.timeout_seconds,
            )
        )

    @abstractmethod
    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        """Retrieve database-search results."""

    def backward(self, work_identifier: str, *, limit: int) -> list[WorkRecord]:
        raise UnsupportedCapabilityError(f"{self.name} does not support backward citation search")

    def forward(self, work_identifier: str, *, limit: int) -> list[WorkRecord]:
        raise UnsupportedCapabilityError(f"{self.name} does not support forward citation search")

    def author_works(self, author_identifier: str, *, limit: int) -> list[WorkRecord]:
        raise UnsupportedCapabilityError(f"{self.name} does not support author expansion")
