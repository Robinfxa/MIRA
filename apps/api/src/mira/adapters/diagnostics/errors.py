"""Compatibility import for the transport-independent safe error catalogue."""
from mira.application.diagnostic_errors import SafeFailure, classify_failure, failure_for

__all__ = ["SafeFailure", "classify_failure", "failure_for"]
