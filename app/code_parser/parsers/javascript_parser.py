"""
JavaScript code parser using regex patterns.

Extracts functions, classes, and imports from JavaScript source code.
"""

import re
from typing import List

from ..schemas import ClassInfo, FunctionInfo, ImportInfo, ParsedFileResult
from .base import BaseLanguageParser


class JavaScriptParser(BaseLanguageParser):
    """Parser for JavaScript source files."""

    # Function declaration: function name(params) {}
    FUNCTION_DECL_PATTERN = re.compile(
        r"(?P<async>async\s+)?"
        r"function\s*(?P<generator>\*)?\s*"
        r"(?P<name>\w+)\s*"
        r"\((?P<params>[^)]*)\)",
        re.MULTILINE,
    )

    # Arrow functions: const name = (params) => {} or const name = async (params) => {}
    ARROW_FUNCTION_PATTERN = re.compile(
        r"(?:const|let|var)\s+"
        r"(?P<name>\w+)\s*=\s*"
        r"(?P<async>async\s*)?"
        r"\((?P<params>[^)]*)\)\s*=>",
        re.MULTILINE,
    )

    # Method shorthand in objects: name(params) {} or async name(params) {}
    METHOD_PATTERN = re.compile(
        r"^\s+(?P<async>async\s+)?"
        r"(?P<generator>\*)?\s*"
        r"(?P<name>\w+)\s*"
        r"\((?P<params>[^)]*)\)\s*\{",
        re.MULTILINE,
    )

    # Class declaration
    CLASS_PATTERN = re.compile(
        r"class\s+(?P<name>\w+)"
        r"(?:\s+extends\s+(?P<base>\w+))?"
        r"\s*\{",
        re.MULTILINE,
    )

    # ES6 imports
    IMPORT_PATTERN = re.compile(
        r"import\s+"
        r"(?:"
        r"(?P<default>\w+)\s*,?\s*)?"  # Default import
        r"(?:"
        r"\{\s*(?P<named>[^}]+)\s*\}\s*,?\s*)?"  # Named imports
        r"(?:\*\s+as\s+(?P<namespace>\w+)\s*)?"  # Namespace import
        r"from\s+"
        r"['\"](?P<module>[^'\"]+)['\"]",
        re.MULTILINE,
    )

    # CommonJS require
    REQUIRE_PATTERN = re.compile(
        r"(?:const|let|var)\s+"
        r"(?:"
        r"(?P<name>\w+)|"
        r"\{\s*(?P<destructured>[^}]+)\s*\}"
        r")\s*=\s*"
        r"require\s*\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)",
        re.MULTILINE,
    )

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def extensions(self) -> List[str]:
        return [".js", ".jsx", ".mjs", ".cjs"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse JavaScript source code."""
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
                parse_error=f"JavaScript parse error: {str(e)}",
            )

    def _extract_functions(self, content: str) -> List[FunctionInfo]:
        """Extract function definitions from JavaScript code."""
        functions = []
        seen_names = set()

        # Regular function declarations
        for match in self.FUNCTION_DECL_PATTERN.finditer(content):
            name = match.group("name")
            if name in seen_names:
                continue
            seen_names.add(name)

            line_start = content[: match.start()].count("\n") + 1
            params = self._parse_params(match.group("params") or "")

            functions.append(
                FunctionInfo(
                    name=name,
                    line_start=line_start,
                    params=params,
                    is_async=bool(match.group("async")),
                )
            )

        # Arrow functions assigned to variables
        for match in self.ARROW_FUNCTION_PATTERN.finditer(content):
            name = match.group("name")
            if name in seen_names:
                continue
            seen_names.add(name)

            line_start = content[: match.start()].count("\n") + 1
            params = self._parse_params(match.group("params") or "")

            functions.append(
                FunctionInfo(
                    name=name,
                    line_start=line_start,
                    params=params,
                    is_async=bool(match.group("async")),
                )
            )

        return functions

    def _extract_classes(self, content: str) -> List[ClassInfo]:
        """Extract class definitions from JavaScript code."""
        classes = []

        for match in self.CLASS_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            bases = []
            if match.group("base"):
                bases.append(match.group("base"))

            # Find class end and extract methods
            line_end = self._find_brace_block_end(content, match.end())
            class_end_line = content[:line_end].count("\n") + 1 if line_end else None

            # Extract methods from class body
            class_body = content[match.end() : line_end] if line_end else content[match.end() :]
            methods = self._extract_class_methods(class_body)

            classes.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=class_end_line,
                    methods=methods,
                    bases=bases,
                )
            )

        return classes

    def _extract_imports(self, content: str) -> List[ImportInfo]:
        """Extract import statements from JavaScript code."""
        imports = []

        # ES6 imports
        for match in self.IMPORT_PATTERN.finditer(content):
            module = match.group("module")
            names = []

            if match.group("default"):
                names.append(match.group("default"))

            if match.group("named"):
                for name in match.group("named").split(","):
                    name = name.strip()
                    if " as " in name:
                        name = name.split(" as ")[0].strip()
                    if name:
                        names.append(name)

            if match.group("namespace"):
                names.append(f"* as {match.group('namespace')}")

            imports.append(
                ImportInfo(
                    module=module,
                    names=names,
                    is_relative=module.startswith("."),
                )
            )

        # CommonJS require
        for match in self.REQUIRE_PATTERN.finditer(content):
            module = match.group("module")
            names = []

            if match.group("name"):
                names.append(match.group("name"))

            if match.group("destructured"):
                for name in match.group("destructured").split(","):
                    name = name.strip()
                    if " as " in name or ":" in name:
                        # Handle { foo: bar } or { foo as bar }
                        name = name.split(":")[0].split(" as ")[0].strip()
                    if name:
                        names.append(name)

            imports.append(
                ImportInfo(
                    module=module,
                    names=names,
                    is_relative=module.startswith("."),
                )
            )

        return imports

    def _parse_params(self, params_str: str) -> List[str]:
        """Parse function parameters."""
        if not params_str.strip():
            return []

        params = []
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
                param = self._extract_param_name(current.strip())
                if param:
                    params.append(param)
                current = ""
            else:
                current += char

        param = self._extract_param_name(current.strip())
        if param:
            params.append(param)

        return params

    def _extract_param_name(self, param: str) -> str | None:
        """Extract parameter name, handling destructuring and defaults."""
        if not param:
            return None

        # Handle destructuring { a, b } or [a, b]
        if param.startswith("{") or param.startswith("["):
            return None  # Skip destructured params for simplicity

        # Handle default values: param = default
        param = param.split("=")[0].strip()

        # Handle rest params: ...args
        if param.startswith("..."):
            param = param[3:]

        return param if param else None

    def _find_brace_block_end(self, content: str, start_pos: int) -> int | None:
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

        return pos if depth == 0 else None

    def _extract_class_methods(self, class_body: str) -> List[str]:
        """Extract method names from class body."""
        methods = []

        # Pattern for class methods
        method_pattern = re.compile(
            r"^\s*(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?"
            r"(?P<name>\w+)\s*\([^)]*\)\s*\{",
            re.MULTILINE,
        )

        for match in method_pattern.finditer(class_body):
            name = match.group("name")
            if name and name != "constructor":
                methods.append(name)
            elif name == "constructor":
                methods.insert(0, name)

        return methods
