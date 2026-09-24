"""Domain-specific exceptions used by adapters and orchestration."""


class EvidencePipelineError(RuntimeError):
    """Base pipeline error."""


class ConfigurationError(EvidencePipelineError):
    """Study configuration is missing or inconsistent."""


class SourceError(EvidencePipelineError):
    """Base source-adapter error."""


class SourceUnavailableError(SourceError):
    """A source is temporarily unavailable after retries."""


class SourceRequestError(SourceError):
    """A source rejected a request permanently."""


class UnsupportedCapabilityError(SourceError):
    """The source does not implement a requested discovery capability."""


class HttpStatusError(SourceError):
    """HTTP response outside the successful range."""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(f"HTTP {status_code}: {message}".strip())
        self.status_code = status_code


class TransportError(SourceError):
    """Network transport failed before a valid response was received."""
