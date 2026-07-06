"""Backward-compatible shim — re-exports from seeker_os.validation.

The validator has been relocated to seeker_os/validation/__init__.py and
is now artifact-agnostic (supports resume, cover_letter, application_answer).
This shim preserves existing imports from seeker_os.resume.validator.
"""

from seeker_os.validation import (
    AccuracyValidator,
    ValidationResult,
    Violation,
    KNOWN_RULE_TYPES,
    ARTIFACT_TYPES,
)

__all__ = [
    "AccuracyValidator",
    "ValidationResult",
    "Violation",
    "KNOWN_RULE_TYPES",
    "ARTIFACT_TYPES",
]
