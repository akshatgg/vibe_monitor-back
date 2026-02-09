"""
Data masking utility for PII protection.

Components:
- mask_secrets(): Fast regex for secrets in logs (AWS keys, tokens, etc.)
- redact_query_for_log(): Shows "[QUERY: X chars]" for safe logging
- PIIMapper: Reversible Presidio masking for customer queries
"""

import functools
import logging
import re

from presidio_analyzer import AnalyzerEngine

logger = logging.getLogger(__name__)


# Regex patterns for secret detection in logs
SAFETY_NET_PATTERNS = {
    "aws_key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]+\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "connection_string": re.compile(
        r"(?:postgresql|mysql|mongodb|redis)(?:\+\w+)?://[^\s]+",
        re.IGNORECASE,
    ),
}


def mask_secrets(text: str) -> str:
    """
    Fast regex-only masking for secrets in logs.

    This is a safety net - the primary defense is not logging secrets.
    Only catches: AWS keys, GitHub tokens, Slack tokens, JWTs, DB connection strings.

    Args:
        text: Log message that may accidentally contain secrets

    Returns:
        Text with secrets masked
    """
    if not text or not isinstance(text, str):
        return text

    masked = text
    for name, pattern in SAFETY_NET_PATTERNS.items():
        masked = pattern.sub(f"[{name.upper()}]", masked)

    return masked


# Alias for backward compatibility
def mask_log_message(message: str) -> str:
    """Mask secrets in log messages. Fast regex-only, no Presidio."""
    return mask_secrets(message)


@functools.lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    """
    Thread-safe lazy initialization of Presidio analyzer.

    Uses @lru_cache for thread-safe singleton pattern.
    This is safer than double-checked locking which has race conditions in Python.
    """
    logger.info("Presidio AnalyzerEngine initialized")
    return AnalyzerEngine()


def redact_query_for_log(query: str) -> str:
    """
    Redact a user query for safe logging.

    Args:
        query: User query to redact

    Returns:
        Redacted string like "[QUERY: 45 chars]"
    """
    if not query or not isinstance(query, str):
        return "[EMPTY QUERY]"

    if not query.strip():
        return "[EMPTY QUERY]"

    # Just show length, don't even preview user content in logs
    return f"[QUERY: {len(query)} chars]"


def mask_email_for_context(email: str) -> str:
    """
    Mask email address for safe inclusion in LLM context.

    Masks the domain part while preserving the username for identification.
    Example: "alice@example.com" -> "alice@[REDACTED]"

    Args:
        email: Email address to mask

    Returns:
        Masked email address with domain redacted
    """
    if not email or not isinstance(email, str):
        return email

    # Simple email masking: preserve username, mask domain
    if "@" in email:
        username, domain = email.rsplit("@", 1)
        return f"{username}@[REDACTED]"

    return email


class PIIMapper:
    """
    Reversible PII masking for customer queries.

    Detects PII at entry point, creates numbered placeholders (email1, ip1, etc.),
    and allows unmasking after LLM response.

    Usage:
        mapper = PIIMapper()
        masked_query = mapper.mask("Why is john@acme.com at 192.168.1.50 failing?")
        # masked_query = "Why is email1 at ip1 failing?"

        # After LLM responds with placeholders...
        llm_response = "email1 at ip1 is failing because..."
        user_response = mapper.unmask(llm_response)
        # user_response = "john@acme.com at 192.168.1.50 is failing because..."
    """

    # Entity type to placeholder prefix mapping
    ENTITY_PREFIXES = {
        "EMAIL_ADDRESS": "email",
        "IP_ADDRESS": "ip",
        "PHONE_NUMBER": "phone",
        "PERSON": "user",
        "CREDIT_CARD": "card",
        "US_SSN": "ssn",
    }

    def __init__(self):
        self._pii_to_placeholder: dict[str, str] = {}  # "john@acme.com" -> "email1"
        self._placeholder_to_pii: dict[str, str] = {}  # "email1" -> "john@acme.com"
        self._counters: dict[str, int] = {}  # {"email": 1, "ip": 2, ...}

    def _get_placeholder(self, entity_type: str, original_value: str) -> str:
        """
        Get or create a placeholder for a PII value.

        If the same value appears multiple times, returns the same placeholder.
        If it's a new value, creates a new numbered placeholder.
        """
        # Check if we already have a placeholder for this exact value
        if original_value in self._pii_to_placeholder:
            return self._pii_to_placeholder[original_value]

        # Get prefix for this entity type
        prefix = self.ENTITY_PREFIXES.get(entity_type, "pii")

        # Increment counter for this prefix
        if prefix not in self._counters:
            self._counters[prefix] = 0
        self._counters[prefix] += 1

        # Create placeholder
        placeholder = f"{prefix}{self._counters[prefix]}"

        # Store bidirectional mapping
        self._pii_to_placeholder[original_value] = placeholder
        self._placeholder_to_pii[placeholder] = original_value

        return placeholder

    def mask(self, text: str) -> str:
        """
        Mask PII in text with numbered placeholders.

        Args:
            text: Text that may contain PII

        Returns:
            Text with PII replaced by placeholders (email1, ip1, etc.)

        Raises:
            RuntimeError: If PII masking fails (fail-closed for security)
        """
        if not text or not isinstance(text, str):
            return text

        try:
            # First apply fast regex for secrets (non-reversible, security critical)
            masked_text = mask_secrets(text)

            # Use Presidio to detect PII entities
            analyzer = _get_analyzer()

            results = analyzer.analyze(
                text=masked_text,
                entities=list(self.ENTITY_PREFIXES.keys()),
                language="en",
                score_threshold=0.5,
            )

            if not results:
                return masked_text

            # Sort results by start position in reverse order
            # (so we can replace from end to start without messing up positions)
            sorted_results = sorted(results, key=lambda x: x.start, reverse=True)

            # Replace each detected entity with a placeholder
            result_text = masked_text
            for result in sorted_results:
                original_value = masked_text[result.start : result.end]
                placeholder = self._get_placeholder(result.entity_type, original_value)
                result_text = (
                    result_text[: result.start]
                    + placeholder
                    + result_text[result.end :]
                )

            return result_text

        except Exception as e:
            logger.error(
                f"CRITICAL: PII masking failed - cannot process query safely: {e}",
                exc_info=True,
            )
            # FAIL CLOSED - raise exception instead of returning unmasked text
            # This prevents PII from leaking through if Presidio is unavailable
            raise RuntimeError(
                "PII masking is currently unavailable. Cannot process query safely."
            ) from e

    def unmask(self, text: str) -> str:
        """
        Replace placeholders back with original PII values.

        Args:
            text: Text containing placeholders (email1, ip1, etc.)

        Returns:
            Text with placeholders replaced by original values
        """
        if not text or not isinstance(text, str):
            return text

        if not self._placeholder_to_pii:
            return text

        result = text
        # Sort by placeholder length descending to avoid partial replacements
        # e.g., replace "email10" before "email1"
        sorted_placeholders = sorted(
            self._placeholder_to_pii.keys(), key=len, reverse=True
        )

        for placeholder in sorted_placeholders:
            original = self._placeholder_to_pii[placeholder]
            # Use word boundary regex to prevent partial matches
            # e.g., email1 in "email10" should not be replaced
            pattern = r"\b" + re.escape(placeholder) + r"\b"
            result = re.sub(pattern, original, result)

        return result

    def get_mapping(self) -> dict[str, str]:
        """
        Get the PII to placeholder mapping (for passing through pipeline).

        Returns:
            Dict mapping original PII values to placeholders
        """
        return self._pii_to_placeholder.copy()

    def get_reverse_mapping(self) -> dict[str, str]:
        """
        Get the placeholder to PII mapping (for unmasking).

        Returns:
            Dict mapping placeholders to original PII values
        """
        return self._placeholder_to_pii.copy()

    @classmethod
    def from_mapping(cls, reverse_mapping: dict[str, str]) -> "PIIMapper":
        """
        Create a PIIMapper from an existing reverse mapping.

        Useful for reconstructing mapper at unmask time from stored mapping.

        Args:
            reverse_mapping: Dict mapping placeholders to original values

        Returns:
            PIIMapper instance with the mapping loaded
        """
        mapper = cls()
        mapper._placeholder_to_pii = reverse_mapping.copy()
        mapper._pii_to_placeholder = {v: k for k, v in reverse_mapping.items()}
        return mapper
