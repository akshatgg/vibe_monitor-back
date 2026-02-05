"""
TypeScript code parser using regex patterns.

Extends JavaScript parser with TypeScript-specific features.
"""

import re
from typing import List

from ..schemas import ClassInfo, FunctionInfo, ParsedFileResult
from .javascript_parser import JavaScriptParser


class TypeScriptParser(JavaScriptParser):
    """Parser for TypeScript source files."""

    # TypeScript-specific function pattern with type annotations
    TS_FUNCTION_PATTERN = re.compile(
        r"(?P<async>async\s+)?"
        r"function\s*(?P<generator>\*)?\s*"
        r"(?P<name>\w+)\s*"
        r"(?:<[^>]+>)?\s*"  # Generic type parameters
        r"\((?P<params>[^)]*)\)"
        r"(?:\s*:\s*(?P<return_type>[^{]+))?"  # Return type
        r"\s*\{",
        re.MULTILINE,
    )

    # TypeScript arrow function with type annotations
    TS_ARROW_FUNCTION_PATTERN = re.compile(
        r"(?:const|let|var)\s+"
        r"(?P<name>\w+)\s*"
        r"(?::\s*[^=]+)?\s*"  # Optional type annotation
        r"=\s*"
        r"(?P<async>async\s*)?"
        r"(?:<[^>]+>)?\s*"  # Generic type parameters
        r"\((?P<params>[^)]*)\)"
        r"(?:\s*:\s*(?P<return_type>[^=]+))?"  # Return type
        r"\s*=>",
        re.MULTILINE,
    )

    # TypeScript interface
    INTERFACE_PATTERN = re.compile(
        r"(?:export\s+)?interface\s+"
        r"(?P<name>\w+)"
        r"(?:<[^>]+>)?"  # Generic type parameters
        r"(?:\s+extends\s+(?P<extends>[^{]+))?"
        r"\s*\{",
        re.MULTILINE,
    )

    # TypeScript type alias
    TYPE_ALIAS_PATTERN = re.compile(
        r"(?:export\s+)?type\s+"
        r"(?P<name>\w+)"
        r"(?:<[^>]+>)?\s*"  # Generic type parameters
        r"=",
        re.MULTILINE,
    )

    # TypeScript enum
    ENUM_PATTERN = re.compile(
        r"(?:export\s+)?(?:const\s+)?enum\s+"
        r"(?P<name>\w+)\s*\{",
        re.MULTILINE,
    )

    @property
    def language(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> List[str]:
        return [".ts", ".tsx"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse TypeScript source code."""
        try:
            functions = self._extract_functions(content)
            classes = self._extract_classes(content)
            imports = self._extract_imports(content)
            line_count = self._count_lines(content)

            # Add TypeScript-specific extractions
            interfaces = self._extract_interfaces(content)
            classes.extend(interfaces)

            return ParsedFileResult(
                functions=functions,
                classes=classes,
                imports=imports,
                line_count=line_count,
            )
        except Exception as e:
            return ParsedFileResult(
                line_count=self._count_lines(content),
                parse_error=f"TypeScript parse error: {str(e)}",
            )

    def _extract_functions(self, content: str) -> List[FunctionInfo]:
        """Extract function definitions from TypeScript code."""
        functions = []
        seen_names = set()

        # TypeScript function declarations
        for match in self.TS_FUNCTION_PATTERN.finditer(content):
            name = match.group("name")
            if name in seen_names:
                continue
            seen_names.add(name)

            line_start = content[: match.start()].count("\n") + 1
            params = self._parse_ts_params(match.group("params") or "")
            return_type = match.group("return_type")

            functions.append(
                FunctionInfo(
                    name=name,
                    line_start=line_start,
                    params=params,
                    is_async=bool(match.group("async")),
                    return_type=return_type.strip() if return_type else None,
                )
            )

        # TypeScript arrow functions
        for match in self.TS_ARROW_FUNCTION_PATTERN.finditer(content):
            name = match.group("name")
            if name in seen_names:
                continue
            seen_names.add(name)

            line_start = content[: match.start()].count("\n") + 1
            params = self._parse_ts_params(match.group("params") or "")
            return_type = match.group("return_type")

            functions.append(
                FunctionInfo(
                    name=name,
                    line_start=line_start,
                    params=params,
                    is_async=bool(match.group("async")),
                    return_type=return_type.strip() if return_type else None,
                )
            )

        # Also use base class extraction for standard JS patterns
        base_functions = super()._extract_functions(content)
        for func in base_functions:
            if func.name not in seen_names:
                functions.append(func)
                seen_names.add(func.name)

        return functions

    def _extract_interfaces(self, content: str) -> List[ClassInfo]:
        """Extract TypeScript interfaces and type aliases."""
        interfaces = []

        # Interfaces
        for match in self.INTERFACE_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            bases = []
            if match.group("extends"):
                for base in match.group("extends").split(","):
                    base = base.strip()
                    if base:
                        bases.append(base)

            # Find interface end
            line_end = self._find_brace_block_end(content, match.end())
            end_line = content[:line_end].count("\n") + 1 if line_end else None

            # Extract interface members
            interface_body = content[match.end() : line_end] if line_end else ""
            methods = self._extract_interface_methods(interface_body)

            interfaces.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=end_line,
                    methods=methods,
                    bases=bases,
                    decorators=["interface"],  # Mark as interface
                )
            )

        # Enums (treat as classes)
        for match in self.ENUM_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            line_end = self._find_brace_block_end(content, match.end())
            end_line = content[:line_end].count("\n") + 1 if line_end else None

            interfaces.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=end_line,
                    decorators=["enum"],
                )
            )

        return interfaces

    def _extract_interface_methods(self, body: str) -> List[str]:
        """Extract method signatures from interface body."""
        methods = []

        # Pattern for interface method signatures
        method_pattern = re.compile(r"^\s*(?P<name>\w+)\s*(?:<[^>]+>)?\s*\([^)]*\)", re.MULTILINE)

        for match in method_pattern.finditer(body):
            name = match.group("name")
            if name:
                methods.append(name)

        return methods

    def _parse_ts_params(self, params_str: str) -> List[str]:
        """Parse TypeScript function parameters, handling type annotations."""
        if not params_str.strip():
            return []

        params = []
        depth = 0
        current = ""

        for char in params_str:
            if char in "([{<":
                depth += 1
                current += char
            elif char in ")]}>":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                param = self._extract_ts_param_name(current.strip())
                if param:
                    params.append(param)
                current = ""
            else:
                current += char

        param = self._extract_ts_param_name(current.strip())
        if param:
            params.append(param)

        return params

    def _extract_ts_param_name(self, param: str) -> str | None:
        """Extract parameter name from TypeScript parameter with type annotation."""
        if not param:
            return None

        # Handle destructuring
        if param.startswith("{") or param.startswith("["):
            return None

        # Remove type annotation (everything after :)
        # But be careful with default values containing colons
        parts = param.split(":")
        param = parts[0].strip()

        # Handle default values: param = default
        param = param.split("=")[0].strip()

        # Handle optional params: param?
        param = param.rstrip("?")

        # Handle rest params: ...args
        if param.startswith("..."):
            param = param[3:]

        return param if param else None
