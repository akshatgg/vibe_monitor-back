"""
Java code parser using regex patterns.

Extracts methods, classes, interfaces, and imports from Java source code.
"""

import re
from typing import List

from ..schemas import ClassInfo, FunctionInfo, ImportInfo, ParsedFileResult
from .base import BaseLanguageParser


class JavaParser(BaseLanguageParser):
    """Parser for Java source files."""

    # Method pattern
    # Handles: public static void methodName(Type param1, Type param2) throws Exception {}
    METHOD_PATTERN = re.compile(
        r"^\s*"
        r"(?P<annotations>(?:@\w+(?:\([^)]*\))?\s*)*)"  # Annotations
        r"(?P<modifiers>(?:(?:public|private|protected|static|final|abstract|synchronized|native|strictfp)\s+)*)"
        r"(?P<generics><[^>]+>\s*)?"  # Generic type parameters
        r"(?P<return_type>[\w<>\[\],\s?]+)\s+"  # Return type
        r"(?P<name>\w+)\s*"  # Method name
        r"\((?P<params>[^)]*)\)"  # Parameters
        r"(?:\s*throws\s+[\w,\s]+)?"  # Optional throws clause
        r"\s*\{",
        re.MULTILINE,
    )

    # Constructor pattern (similar to method but no return type)
    CONSTRUCTOR_PATTERN = re.compile(
        r"^\s*"
        r"(?P<annotations>(?:@\w+(?:\([^)]*\))?\s*)*)"
        r"(?:public|private|protected)?\s*"
        r"(?P<name>\w+)\s*"  # Constructor name (same as class name)
        r"\((?P<params>[^)]*)\)"
        r"(?:\s*throws\s+[\w,\s]+)?"
        r"\s*\{",
        re.MULTILINE,
    )

    # Class pattern
    CLASS_PATTERN = re.compile(
        r"^\s*"
        r"(?P<annotations>(?:@\w+(?:\([^)]*\))?\s*)*)"
        r"(?P<modifiers>(?:(?:public|private|protected|static|final|abstract)\s+)*)"
        r"class\s+"
        r"(?P<name>\w+)"
        r"(?P<generics><[^>]+>)?"  # Generic type parameters
        r"(?:\s+extends\s+(?P<extends>[\w<>,\s]+))?"  # Extends clause
        r"(?:\s+implements\s+(?P<implements>[\w<>,\s]+))?"  # Implements clause
        r"\s*\{",
        re.MULTILINE,
    )

    # Interface pattern
    INTERFACE_PATTERN = re.compile(
        r"^\s*"
        r"(?P<annotations>(?:@\w+(?:\([^)]*\))?\s*)*)"
        r"(?P<modifiers>(?:(?:public|private|protected|static)\s+)*)"
        r"interface\s+"
        r"(?P<name>\w+)"
        r"(?P<generics><[^>]+>)?"
        r"(?:\s+extends\s+(?P<extends>[\w<>,\s]+))?"
        r"\s*\{",
        re.MULTILINE,
    )

    # Enum pattern
    ENUM_PATTERN = re.compile(
        r"^\s*"
        r"(?P<annotations>(?:@\w+(?:\([^)]*\))?\s*)*)"
        r"(?P<modifiers>(?:(?:public|private|protected|static)\s+)*)"
        r"enum\s+"
        r"(?P<name>\w+)"
        r"(?:\s+implements\s+(?P<implements>[\w<>,\s]+))?"
        r"\s*\{",
        re.MULTILINE,
    )

    # Import pattern
    IMPORT_PATTERN = re.compile(
        r"^import\s+(?P<static>static\s+)?(?P<module>[\w.]+)(?:\.\*)?;",
        re.MULTILINE,
    )

    # Package pattern
    PACKAGE_PATTERN = re.compile(
        r"^package\s+(?P<package>[\w.]+);",
        re.MULTILINE,
    )

    @property
    def language(self) -> str:
        return "java"

    @property
    def extensions(self) -> List[str]:
        return [".java"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse Java source code."""
        try:
            functions = self._extract_methods(content)
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
                parse_error=f"Java parse error: {str(e)}",
            )

    def _extract_methods(self, content: str) -> List[FunctionInfo]:
        """Extract method definitions from Java code."""
        methods = []
        seen = set()

        for match in self.METHOD_PATTERN.finditer(content):
            name = match.group("name")

            # Skip common false positives (control structures)
            if name in ("if", "while", "for", "switch", "catch", "synchronized"):
                continue

            line_start = content[: match.start()].count("\n") + 1

            # Create unique key to avoid duplicates
            key = (name, line_start)
            if key in seen:
                continue
            seen.add(key)

            # Parse parameters
            params = self._parse_params(match.group("params") or "")

            # Extract annotations as decorators
            annotations_str = match.group("annotations") or ""
            decorators = self._extract_annotations(annotations_str)

            # Check if async (Java doesn't have built-in async, but check for common patterns)
            modifiers = match.group("modifiers") or ""
            is_async = "CompletableFuture" in (match.group("return_type") or "")

            # Get return type
            return_type = match.group("return_type")
            if return_type:
                return_type = return_type.strip()

            # Find method end
            line_end = self._find_brace_block_end_line(content, match.end())

            methods.append(
                FunctionInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    params=params,
                    decorators=decorators,
                    is_async=is_async,
                    return_type=return_type,
                )
            )

        return methods

    def _extract_classes(self, content: str) -> List[ClassInfo]:
        """Extract class, interface, and enum definitions from Java code."""
        classes = []

        # Classes
        for match in self.CLASS_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            # Extract base classes
            bases = []
            if match.group("extends"):
                bases.append(match.group("extends").strip())
            if match.group("implements"):
                for impl in match.group("implements").split(","):
                    impl = impl.strip()
                    if impl:
                        bases.append(impl)

            # Extract annotations as decorators
            annotations_str = match.group("annotations") or ""
            decorators = self._extract_annotations(annotations_str)

            # Find class end and extract methods
            line_end = self._find_brace_block_end_line(content, match.end())
            class_body = content[match.end() : self._find_brace_block_end_pos(content, match.end())]
            methods = self._extract_class_method_names(class_body)

            classes.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    methods=methods,
                    bases=bases,
                    decorators=decorators,
                )
            )

        # Interfaces
        for match in self.INTERFACE_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            bases = []
            if match.group("extends"):
                for ext in match.group("extends").split(","):
                    ext = ext.strip()
                    if ext:
                        bases.append(ext)

            annotations_str = match.group("annotations") or ""
            decorators = self._extract_annotations(annotations_str)
            decorators.append("interface")

            line_end = self._find_brace_block_end_line(content, match.end())
            interface_body = content[match.end() : self._find_brace_block_end_pos(content, match.end())]
            methods = self._extract_interface_method_names(interface_body)

            classes.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    methods=methods,
                    bases=bases,
                    decorators=decorators,
                )
            )

        # Enums
        for match in self.ENUM_PATTERN.finditer(content):
            name = match.group("name")
            line_start = content[: match.start()].count("\n") + 1

            bases = []
            if match.group("implements"):
                for impl in match.group("implements").split(","):
                    impl = impl.strip()
                    if impl:
                        bases.append(impl)

            annotations_str = match.group("annotations") or ""
            decorators = self._extract_annotations(annotations_str)
            decorators.append("enum")

            line_end = self._find_brace_block_end_line(content, match.end())

            classes.append(
                ClassInfo(
                    name=name,
                    line_start=line_start,
                    line_end=line_end,
                    bases=bases,
                    decorators=decorators,
                )
            )

        return classes

    def _extract_imports(self, content: str) -> List[ImportInfo]:
        """Extract import statements from Java code."""
        imports = []

        for match in self.IMPORT_PATTERN.finditer(content):
            module = match.group("module")
            is_static = bool(match.group("static"))

            # Extract the simple class name
            parts = module.split(".")
            names = [parts[-1]] if parts else []

            imports.append(
                ImportInfo(
                    module=module,
                    names=names,
                    alias="static" if is_static else None,
                )
            )

        return imports

    def _parse_params(self, params_str: str) -> List[str]:
        """Parse Java method parameters."""
        if not params_str.strip():
            return []

        params = []
        depth = 0
        current = ""

        for char in params_str:
            if char in "<([{":
                depth += 1
                current += char
            elif char in ">)]}":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                param = self._extract_java_param_name(current.strip())
                if param:
                    params.append(param)
                current = ""
            else:
                current += char

        param = self._extract_java_param_name(current.strip())
        if param:
            params.append(param)

        return params

    def _extract_java_param_name(self, param: str) -> str | None:
        """Extract parameter name from Java parameter declaration."""
        if not param:
            return None

        # Handle annotations: @NotNull String name
        param = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", param)

        # Handle final modifier: final String name
        param = re.sub(r"\bfinal\s+", "", param)

        # Java params are: Type name or Type... name (varargs)
        parts = param.split()
        if len(parts) >= 2:
            # Last part is the name, second-to-last might have ... for varargs
            return parts[-1]
        elif len(parts) == 1:
            # Might just be the name if type is implicit (rare in Java)
            return parts[0]

        return None

    def _extract_annotations(self, annotations_str: str) -> List[str]:
        """Extract annotation names from annotations string."""
        if not annotations_str:
            return []

        annotations = []
        for match in re.finditer(r"@(\w+)", annotations_str):
            annotations.append(match.group(1))

        return annotations

    def _extract_class_method_names(self, body: str) -> List[str]:
        """Extract method names from class body."""
        methods = []

        method_pattern = re.compile(
            r"(?:public|private|protected|static|final|abstract|synchronized|native)?\s*"
            r"(?:[\w<>\[\],\s?]+)\s+"
            r"(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{",
            re.MULTILINE,
        )

        for match in method_pattern.finditer(body):
            name = match.group(1)
            if name and name not in ("if", "while", "for", "switch", "catch", "synchronized"):
                methods.append(name)

        return methods

    def _extract_interface_method_names(self, body: str) -> List[str]:
        """Extract method signatures from interface body."""
        methods = []

        # Interface methods don't have body (unless default)
        method_pattern = re.compile(
            r"(?:default\s+)?(?:[\w<>\[\],\s?]+)\s+"
            r"(\w+)\s*\([^)]*\)",
            re.MULTILINE,
        )

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
