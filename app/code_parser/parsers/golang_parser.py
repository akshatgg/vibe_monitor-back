"""
Go code parser using regex patterns.

Extracts functions, structs, interfaces, and imports from Go source code.
"""

import re
from typing import List

from ..schemas import ClassInfo, FunctionInfo, ImportInfo, ParsedFileResult
from .base import BaseLanguageParser


class GolangParser(BaseLanguageParser):
    """Parser for Go source files."""

    # Function pattern: func name(params) return_type {}
    # Also handles receiver: func (r *Receiver) name(params) return_type {}
    FUNCTION_PATTERN = re.compile(
        r"^func\s+"
        r"(?:\((?P<receiver>[^)]+)\)\s+)?"  # Optional receiver
        r"(?P<name>\w+)\s*"
        r"\((?P<params>[^)]*)\)"
        r"(?:\s*\((?P<returns_multi>[^)]+)\))?"  # Multiple return values
        r"(?:\s+(?P<returns_single>\w+(?:\s*\*?\w+)*))?"  # Single return value
        r"\s*\{",
        re.MULTILINE,
    )

    # Struct pattern
    STRUCT_PATTERN = re.compile(
        r"^type\s+(?P<name>\w+)\s+struct\s*\{",
        re.MULTILINE,
    )

    # Interface pattern
    INTERFACE_PATTERN = re.compile(
        r"^type\s+(?P<name>\w+)\s+interface\s*\{",
        re.MULTILINE,
    )

    # Type alias pattern
    TYPE_ALIAS_PATTERN = re.compile(
        r"^type\s+(?P<name>\w+)\s+(?!struct|interface)(?P<type>\w+)",
        re.MULTILINE,
    )

    # Import patterns
    SINGLE_IMPORT_PATTERN = re.compile(
        r'^import\s+"(?P<module>[^"]+)"',
        re.MULTILINE,
    )

    MULTI_IMPORT_PATTERN = re.compile(
        r"^import\s*\(\s*(?P<imports>[\s\S]*?)\s*\)",
        re.MULTILINE,
    )

    @property
    def language(self) -> str:
        return "go"

    @property
    def extensions(self) -> List[str]:
        return [".go"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse Go source code."""
        try:
            functions = self._extract_functions(content)
            classes = self._extract_types(content)
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
                parse_error=f"Go parse error: {str(e)}",
            )

    def _extract_functions(self, content: str) -> List[FunctionInfo]:
        """Extract function definitions from Go code."""
        functions = []

        for match in self.FUNCTION_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            # Parse parameters
            params = self._parse_params(match.group("params") or "")

            # Determine return type
            return_type = None
            if match.group("returns_multi"):
                return_type = f"({match.group('returns_multi')})"
            elif match.group("returns_single"):
                return_type = match.group("returns_single")

            # Check if it's a method (has receiver)
            receiver = match.group("receiver")
            decorators = []
            if receiver:
                # Extract receiver type for context
                receiver_type = receiver.split()[-1].strip("*")
                decorators.append(f"method:{receiver_type}")

            # Find function end
            line_end = self._find_brace_block_end_line(content, match.end())

            functions.append(
                FunctionInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    params=params,
                    return_type=return_type,
                    decorators=decorators,
                )
            )

        return functions

    def _extract_types(self, content: str) -> List[ClassInfo]:
        """Extract struct and interface definitions from Go code."""
        types = []

        # Structs
        for match in self.STRUCT_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1
            line_end = self._find_brace_block_end_line(content, match.end())

            # Extract struct methods (functions with this type as receiver)
            methods = self._extract_struct_methods(content, name)

            types.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    methods=methods,
                    decorators=["struct"],
                )
            )

        # Interfaces
        for match in self.INTERFACE_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1
            line_end = self._find_brace_block_end_line(content, match.end())

            # Extract interface method signatures
            interface_body = content[match.end() : self._find_brace_block_end_pos(content, match.end())]
            methods = self._extract_interface_methods(interface_body)

            types.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    methods=methods,
                    decorators=["interface"],
                )
            )

        return types

    def _extract_imports(self, content: str) -> List[ImportInfo]:
        """Extract import statements from Go code."""
        imports = []

        # Single imports
        for match in self.SINGLE_IMPORT_PATTERN.finditer(content):
            module = match.group("module")
            imports.append(
                ImportInfo(
                    module=module,
                    names=[module.split("/")[-1]],  # Package name is last part of path
                )
            )

        # Multi-line imports
        for match in self.MULTI_IMPORT_PATTERN.finditer(content):
            imports_block = match.group("imports")
            for line in imports_block.split("\n"):
                line = line.strip()
                if not line or line.startswith("//"):
                    continue

                # Handle aliased imports: alias "path/to/pkg"
                alias_match = re.match(r'(\w+)\s+"([^"]+)"', line)
                if alias_match:
                    alias = alias_match.group(1)
                    module = alias_match.group(2)
                    imports.append(
                        ImportInfo(
                            module=module,
                            names=[module.split("/")[-1]],
                            alias=alias if alias != "_" else None,
                        )
                    )
                else:
                    # Simple import: "path/to/pkg"
                    simple_match = re.match(r'"([^"]+)"', line)
                    if simple_match:
                        module = simple_match.group(1)
                        imports.append(
                            ImportInfo(
                                module=module,
                                names=[module.split("/")[-1]],
                            )
                        )

        return imports

    def _parse_params(self, params_str: str) -> List[str]:
        """Parse Go function parameters."""
        if not params_str.strip():
            return []

        params = []
        # Go params can be grouped: (a, b int, c string)
        # Split by comma but handle complex types
        current = ""
        depth = 0

        for char in params_str:
            if char in "([{":
                depth += 1
                current += char
            elif char in ")]}":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                param = self._extract_go_param_name(current.strip())
                if param:
                    params.extend(param)
                current = ""
            else:
                current += char

        param = self._extract_go_param_name(current.strip())
        if param:
            params.extend(param)

        return params

    def _extract_go_param_name(self, param: str) -> List[str]:
        """Extract parameter name(s) from Go parameter declaration."""
        if not param:
            return []

        # Go allows grouped params: a, b int
        # The type is at the end, names are at the beginning
        parts = param.split()
        if not parts:
            return []

        # If last part looks like a type, the rest are names
        # Types typically start with *, [], map, chan, func, or are identifiers
        names = []
        for i, part in enumerate(parts[:-1]):
            # Clean up the name (remove commas)
            name = part.rstrip(",")
            if name and not name.startswith("*") and not name.startswith("["):
                names.append(name)

        # If we only have one part, it might be just the type (empty param name)
        # or it might be a single named param without explicit type
        if len(parts) == 1:
            # Could be variadic: ...Type or just a type name
            if not parts[0].startswith("...") and not parts[0].startswith("*"):
                return [parts[0]]

        return names if names else []

    def _extract_struct_methods(self, content: str, struct_name: str) -> List[str]:
        """Extract methods for a given struct type."""
        methods = []
        pattern = re.compile(
            rf"^func\s+\([^)]*\*?{struct_name}\)\s+(\w+)\s*\(",
            re.MULTILINE,
        )

        for match in pattern.finditer(content):
            methods.append(match.group(1))

        return methods

    def _extract_interface_methods(self, body: str) -> List[str]:
        """Extract method signatures from interface body."""
        methods = []
        method_pattern = re.compile(r"^\s*(\w+)\s*\([^)]*\)", re.MULTILINE)

        for match in method_pattern.finditer(body):
            name = match.group(1)
            if name:
                methods.append(name)

        return methods

    def _find_brace_block_end_pos(self, content: str, start_pos: int) -> int:
        """Find the position of the closing brace for a block."""
        depth = 1
        pos = start_pos

        while pos < len(content) and depth > 0:
            char = content[pos]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            pos += 1

        return pos

    def _find_brace_block_end_line(self, content: str, start_pos: int) -> int | None:
        """Find the line number of the closing brace for a block."""
        end_pos = self._find_brace_block_end_pos(content, start_pos)
        if end_pos and end_pos <= len(content):
            return content[:end_pos].count("\n") + 1
        return None
