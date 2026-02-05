"""
Base parser interface for language-specific code parsers.

All language parsers should inherit from BaseLanguageParser.
"""

from abc import ABC, abstractmethod
from typing import List

from ..schemas import ParsedFileResult


class BaseLanguageParser(ABC):
    """
    Abstract base class for language-specific code parsers.

    Each language parser implements regex-based extraction of
    functions, classes, and imports from source code.
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

        Args:
            content: Source code content as string
            file_path: Path to the file (for context/logging)

        Returns:
            ParsedFileResult with extracted code structures
        """
        ...

    def _count_lines(self, content: str) -> int:
        """Count the number of lines in the content."""
        if not content:
            return 0
        return content.count("\n") + (1 if not content.endswith("\n") else 0)

    def _extract_docstring(self, content: str, start_line: int, max_chars: int = 500) -> str | None:
        """
        Extract docstring from function/class definition.

        Args:
            content: Full source code
            start_line: Line number where the function/class starts (1-indexed)
            max_chars: Maximum characters to extract

        Returns:
            Docstring content or None
        """
        lines = content.split("\n")
        if start_line < 1 or start_line > len(lines):
            return None

        # Look for docstring in the next few lines
        for i in range(start_line, min(start_line + 5, len(lines))):
            line = lines[i].strip()

            # Check for triple-quoted strings
            for quote in ['"""', "'''"]:
                if line.startswith(quote):
                    # Find the end of the docstring
                    docstring_lines = []
                    if line.endswith(quote) and len(line) > 6:
                        # Single-line docstring
                        return line[3:-3][:max_chars]

                    # Multi-line docstring
                    docstring_lines.append(line[3:])
                    for j in range(i + 1, len(lines)):
                        end_line = lines[j]
                        if quote in end_line:
                            idx = end_line.find(quote)
                            docstring_lines.append(end_line[:idx])
                            break
                        docstring_lines.append(end_line)

                    return "\n".join(docstring_lines).strip()[:max_chars]

        return None
