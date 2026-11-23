"""Custom exceptions shared by all repository implementations."""
from __future__ import annotations


class RepositoryError(Exception):
    """Base class so the UI can catch every repo failure in one place."""


class ValidationError(RepositoryError):
    """Input rejected at the boundary (empty title, bad assignee, too long...)."""


class NotFoundError(RepositoryError):
    """No active (non-archived) row with the given id."""


class BackendError(RepositoryError):
    """The storage backend failed (network, permissions, unexpected response)."""


class AuthError(RepositoryError):
    """Sign-in or session restore failed."""
