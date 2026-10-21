"""Application-level errors raised by infrastructure adapters."""


class ProviderError(Exception):
    """Raised when an external provider call fails."""


class ApplicationError(Exception):
    """Base class for errors surfaced by application use cases."""


class InvalidDateReference(ApplicationError):
    """Raised when a date reference cannot be resolved to a concrete day."""
