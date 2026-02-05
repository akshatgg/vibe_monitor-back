"""
Parser Registry - manages language-specific code parsers.

Provides a unified interface to get the appropriate parser for a given file.
"""

import logging
from typing import Dict, Optional

from .base import BaseLanguageParser
from .constants import EXTENSION_TO_LANGUAGE, get_language_for_file
from .golang_parser import GolangParser
from .java_parser import JavaParser
from .javascript_parser import JavaScriptParser
from .python_parser import PythonParser
from .typescript_parser import TypeScriptParser

logger = logging.getLogger(__name__)


class ParserRegistry:
    """
    Registry for language-specific code parsers.

    Provides methods to get parsers by language name or file extension.
    """

    def __init__(self):
        """Initialize the parser registry with all supported parsers."""
        self._parsers: Dict[str, BaseLanguageParser] = {
            "python": PythonParser(),
            "javascript": JavaScriptParser(),
            "typescript": TypeScriptParser(),
            "go": GolangParser(),
            "java": JavaParser(),
        }

        logger.info(f"ParserRegistry initialized with {len(self._parsers)} language parsers")

    def get_parser(self, language: str) -> Optional[BaseLanguageParser]:
        """
        Get parser by language name.

        Args:
            language: Language name (e.g., 'python', 'javascript')

        Returns:
            Parser instance or None if language not supported
        """
        return self._parsers.get(language.lower())

    def get_parser_for_file(self, file_path: str) -> Optional[BaseLanguageParser]:
        """
        Get parser for a file based on its extension.

        Args:
            file_path: Path to the file

        Returns:
            Parser instance or None if file type not supported
        """
        language = get_language_for_file(file_path)
        if language:
            return self.get_parser(language)
        return None

    def get_language_for_file(self, file_path: str) -> Optional[str]:
        """
        Get the language name for a file based on its extension.

        Args:
            file_path: Path to the file

        Returns:
            Language name or None if not supported
        """
        return get_language_for_file(file_path)

    @property
    def supported_languages(self) -> list[str]:
        """Return list of supported language names."""
        return list(self._parsers.keys())

    @property
    def supported_extensions(self) -> list[str]:
        """Return list of all supported file extensions."""
        return list(EXTENSION_TO_LANGUAGE.keys())


# Global parser registry instance
_registry: Optional[ParserRegistry] = None


def get_parser_registry() -> ParserRegistry:
    """Get the global parser registry instance (singleton)."""
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
    return _registry


__all__ = [
    "ParserRegistry",
    "get_parser_registry",
    "BaseLanguageParser",
    "PythonParser",
    "JavaScriptParser",
    "TypeScriptParser",
    "GolangParser",
    "JavaParser",
]
