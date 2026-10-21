"""Domain exceptions."""


class DomainError(Exception):
    """Base class for errors raised by the domain layer."""


class InvalidClientUserId(DomainError):
    """Raised when a client user id is empty or blank."""


class InvalidAmount(DomainError):
    """Raised when a monetary amount is not a positive integer of cents."""


class InvalidEntry(DomainError):
    """Raised when an entry is missing required data."""
