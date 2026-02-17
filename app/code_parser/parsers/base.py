"""
Base parser interface for language-specific code parsers.

All language parsers should inherit from BaseLanguageParser.
"""

from abc import ABC, abstractmethod
from typing import List

from ..schemas import ExtractedFacts, ParsedFileResult


class BaseLanguageParser(ABC):
    """
    Abstract base class for language-specific code parsers.

    Each language parser uses Tree-sitter for AST-based extraction of
    functions, classes, imports, and code facts for gap detection.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language name (e.g., 'python', 'javascript')."""
        ...

    @property
    @abstractmethod
    def extensions(self) -> List[str]:
        """Return supported file extensions (e.g., ['.py'])."""
        ...

    @abstractmethod
    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """
        Parse source code and extract functions, classes, and imports.

        This method provides backward-compatible output stored in the DB.

        Args:
            content: Source code content as string
            file_path: Path to the file (for context/logging)

        Returns:
            ParsedFileResult with extracted code structures
        """
        ...

    @abstractmethod
    def extract_facts(self, content: str, file_path: str) -> ExtractedFacts:
        """
        Extract structured code facts for the rule engine.

        Facts include functions, classes, try/except blocks, logging calls,
        metrics calls, HTTP handlers, external I/O, imports, and decorators.

        Args:
            content: Source code content as string
            file_path: Path to the file

        Returns:
            ExtractedFacts with all detected code facts
        """
        ...

    def _count_lines(self, content: str) -> int:
        """Count the number of lines in the content."""
        if not content:
            return 0
        return content.count("\n") + (1 if not content.endswith("\n") else 0)
