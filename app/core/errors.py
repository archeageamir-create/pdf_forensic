class ForensicsError(Exception):
    """Base exception for expected application errors."""


class UnsupportedFileError(ForensicsError):
    """Raised when a user selects an unsupported document type."""


class EvidencePreparationError(ForensicsError):
    """Raised when an immutable working copy cannot be prepared safely."""


class AnalysisError(ForensicsError):
    """Raised when an analyzer cannot process its input."""

