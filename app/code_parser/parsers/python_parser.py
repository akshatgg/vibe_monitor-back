"""
Python code parser using regex patterns.

Extracts functions, classes, and imports from Python source code.
"""

import re
from typing import List

from ..schemas import ClassInfo, FunctionInfo, ImportInfo, ParsedFileResult
from .base import BaseLanguageParser


class PythonParser(BaseLanguageParser):
    """Parser for Python source files."""

    # Regex patterns for Python code structures
    # Function pattern: handles decorators, async, and type hints
    FUNCTION_PATTERN = re.compile(
        r"^(?P<decorators>(?:@[\w.]+(?:\([^)]*\))?\s*\n)*)"  # Decorators
        r"(?P<async>async\s+)?"  # Optional async
        r"def\s+(?P<name>\w+)\s*"  # Function name
        r"\((?P<params>[^)]*)\)"  # Parameters
        r"(?:\s*->\s*(?P<return_type>[^:]+))?"  # Optional return type
        r"\s*:",  # Colon
        re.MULTILINE,
    )

    # Class pattern: handles decorators and inheritance
    CLASS_PATTERN = re.compile(
        r"^(?P<decorators>(?:@[\w.]+(?:\([^)]*\))?\s*\n)*)"  # Decorators
        r"class\s+(?P<name>\w+)"  # Class name
        r"(?:\s*\((?P<bases>[^)]*)\))?"  # Optional base classes
        r"\s*:",  # Colon
        re.MULTILINE,
    )

    # Import patterns
    IMPORT_PATTERN = re.compile(
        r"^(?P<from>from\s+(?P<from_module>\.{0,3}[\w.]*)\s+)?"
        r"import\s+(?P<imports>.+?)$",
        re.MULTILINE,
    )

    @property
    def language(self) -> str:
        return "python"

    @property
    def extensions(self) -> List[str]:
        return [".py"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse Python source code."""
        try:
            functions = self._extract_functions(content)
            classes = self._extract_classes(content)
            imports = self._extract_imports(content)
            line_count = self._count_lines(content)

            return ParsedFileResult(
                functions=functions,
                classes=classes,
                imports=imports,
                line_count=line_count,
            )
        except Exception as e:
            return ParsedFileResult(
                line_count=self._count_lines(content),
                parse_error=f"Python parse error: {str(e)}",
            )

    def _extract_functions(self, content: str) -> List[FunctionInfo]:
        """Extract function definitions from Python code."""
        functions = []
        lines = content.split("\n")

        for match in self.FUNCTION_PATTERN.finditer(content):
            # Calculate line number
            line_start = content[: match.start()].count("\n") + 1

            # Extract decorator names
            decorators_str = match.group("decorators") or ""
            decorators = []
            for deco_match in re.finditer(r"@([\w.]+)", decorators_str):
                decorators.append(deco_match.group(1))

            # Parse parameters
            params_str = match.group("params") or ""
            params = self._parse_params(params_str)

            # Determine end line (find next function/class at same or lower indent)
            line_end = self._find_block_end(lines, line_start - 1)

            functions.append(
                FunctionInfo(
                    name=match.group("name"),
                    line_start=line_start,
                    line_end=line_end,
                    params=params,
                    decorators=decorators,
                    is_async=bool(match.group("async")),
                    return_type=match.group("return_type").strip() if match.group("return_type") else None,
                )
            )

        return functions

    def _extract_classes(self, content: str) -> List[ClassInfo]:
        """Extract class definitions from Python code."""
        classes = []
        lines = content.split("\n")

        for match in self.CLASS_PATTERN.finditer(content):
            # Calculate line number
            line_start = content[: match.start()].count("\n") + 1

            # Extract decorator names
            decorators_str = match.group("decorators") or ""
            decorators = []
            for deco_match in re.finditer(r"@([\w.]+)", decorators_str):
                decorators.append(deco_match.group(1))

            # Parse base classes
            bases_str = match.group("bases") or ""
            bases = [b.strip() for b in bases_str.split(",") if b.strip()]

            # Find class end and extract methods
            line_end = self._find_block_end(lines, line_start - 1)

            # Extract method names within the class
            class_content = "\n".join(lines[line_start - 1 : line_end])
            methods = self._extract_method_names(class_content)

            classes.append(
                ClassInfo(
                    name=match.group("name"),
                    line_start=line_start,
                    line_end=line_end,
                    methods=methods,
                    bases=bases,
                    decorators=decorators,
                )
            )

        return classes

    def _extract_imports(self, content: str) -> List[ImportInfo]:
        """Extract import statements from Python code."""
        imports = []

        for match in self.IMPORT_PATTERN.finditer(content):
            if match.group("from"):
                # from X import Y
                module = match.group("from_module")
                imports_str = match.group("imports")
                names = []
                alias = None

                # Handle "from X import (a, b, c)"
                if "(" in imports_str:
                    # Multi-line import, find closing paren
                    start_pos = match.end()
                    paren_content = imports_str
                    if ")" not in paren_content:
                        # Look for closing paren in subsequent content
                        end_pos = content.find(")", start_pos)
                        if end_pos != -1:
                            paren_content = content[match.start() : end_pos + 1]
                            paren_content = paren_content.split("import")[1]

                    # Remove parens and split
                    paren_content = paren_content.replace("(", "").replace(")", "")
                    for name in paren_content.split(","):
                        name = name.strip()
                        if name and not name.startswith("#"):
                            # Handle "name as alias"
                            if " as " in name:
                                name = name.split(" as ")[0].strip()
                            names.append(name)
                else:
                    # Simple import
                    for name in imports_str.split(","):
                        name = name.strip()
                        if name:
                            if " as " in name:
                                parts = name.split(" as ")
                                names.append(parts[0].strip())
                            else:
                                names.append(name)

                is_relative = module.startswith(".")
                imports.append(
                    ImportInfo(
                        module=module,
                        names=names,
                        is_relative=is_relative,
                    )
                )
            else:
                # import X
                imports_str = match.group("imports")
                for module_part in imports_str.split(","):
                    module_part = module_part.strip()
                    if module_part:
                        alias = None
                        if " as " in module_part:
                            parts = module_part.split(" as ")
                            module_part = parts[0].strip()
                            alias = parts[1].strip()

                        imports.append(
                            ImportInfo(
                                module=module_part,
                                alias=alias,
                            )
                        )

        return imports

    def _parse_params(self, params_str: str) -> List[str]:
        """Parse function parameters, handling type hints and defaults."""
        if not params_str.strip():
            return []

        params = []
        # Simple split - doesn't handle complex nested generics perfectly
        depth = 0
        current = ""
        for char in params_str:
            if char in "([{":
                depth += 1
                current += char
            elif char in ")]}":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                param = current.strip()
                if param:
                    # Extract just the parameter name (before : or =)
                    param_name = param.split(":")[0].split("=")[0].strip()
                    if param_name and param_name not in ("self", "cls"):
                        params.append(param_name)
                current = ""
            else:
                current += char

        # Don't forget the last parameter
        param = current.strip()
        if param:
            param_name = param.split(":")[0].split("=")[0].strip()
            if param_name and param_name not in ("self", "cls"):
                params.append(param_name)

        return params

    def _find_block_end(self, lines: List[str], start_idx: int) -> int:
        """Find the end line of a Python block (function/class)."""
        if start_idx >= len(lines):
            return start_idx + 1

        # Get the indentation of the definition line
        start_line = lines[start_idx]
        base_indent = len(start_line) - len(start_line.lstrip())

        # Find the next line at the same or lower indentation level
        for i in range(start_idx + 1, len(lines)):
            line = lines[i]
            if not line.strip():  # Skip empty lines
                continue
            if line.strip().startswith("#"):  # Skip comments
                continue

            current_indent = len(line) - len(line.lstrip())
            if current_indent <= base_indent:
                return i  # Previous line is the end

        # If we reach the end, return the last line
        return len(lines)

    def _extract_method_names(self, class_content: str) -> List[str]:
        """Extract method names from class content."""
        methods = []
        method_pattern = re.compile(r"^\s+(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)

        for match in method_pattern.finditer(class_content):
            methods.append(match.group(1))

        return methods
