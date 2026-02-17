"""
TypeScript code parser using Tree-sitter.

Extends JavaScript parser with TypeScript-specific features.
"""

import logging
from typing import List

from tree_sitter_language_pack import get_parser

from ..schemas import ClassInfo, CodeFact, ParsedFileResult
from .javascript_parser import JavaScriptParser

logger = logging.getLogger(__name__)


class TypeScriptParser(JavaScriptParser):
    """Parser for TypeScript source files using Tree-sitter."""

    def __init__(self):
        self._ts_parser = get_parser("typescript")
        self._tsx_parser = get_parser("tsx")
        self._current_parser = self._ts_parser

    @property
    def language(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> List[str]:
        return [".ts", ".tsx"]

    def _get_ts_parser(self):
        """Return the current parser (ts or tsx based on file)."""
        return self._current_parser

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse TypeScript source code."""
        self._current_parser = self._tsx_parser if file_path.endswith(".tsx") else self._ts_parser
        try:
            tree = self._current_parser.parse(content.encode())
            root = tree.root_node

            functions = self._extract_functions(root)
            classes = self._extract_classes(root)
            imports = self._extract_imports(root)
            line_count = self._count_lines(content)

            # Add TypeScript-specific types (interfaces, enums, type aliases)
            ts_types = self._extract_ts_types(root)
            classes.extend(ts_types)

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

    def extract_facts(self, content: str, file_path: str):
        """Extract facts, using tsx parser for .tsx files."""
        self._current_parser = self._tsx_parser if file_path.endswith(".tsx") else self._ts_parser
        return super().extract_facts(content, file_path)

    def _walk_for_facts(self, node, facts, file_path, parent_func=None, parent_class=None):
        """Extended walk that also handles TypeScript-specific nodes."""
        lang = self.language

        # Interface declaration
        if node.type == "interface_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "interface"},
            ))
            for child in node.named_children:
                self._walk_for_facts(child, facts, file_path, parent_func, parent_class)
            return

        # Type alias declaration
        if node.type == "type_alias_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "type_alias"},
            ))
            return

        # Enum declaration
        if node.type == "enum_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "enum"},
            ))
            return

        # Abstract class declaration
        if node.type == "abstract_class_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "abstract_class"},
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=parent_func, parent_class=name)
            return

        # Delegate to base JS walker for everything else
        super()._walk_for_facts(node, facts, file_path, parent_func, parent_class)

    # ========== TypeScript-Specific Extraction ==========

    def _extract_ts_types(self, root) -> List[ClassInfo]:
        """Extract TypeScript-specific type definitions."""
        types = []
        self._collect_ts_types(root, types)
        return types

    def _collect_ts_types(self, node, types: List[ClassInfo]):
        """Recursively collect TypeScript interfaces, enums, type aliases."""
        if node.type == "interface_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            bases = []
            # Check for extends
            for child in node.named_children:
                if child.type == "extends_type_clause":
                    for inner in child.named_children:
                        if inner.type in ("type_identifier", "generic_type"):
                            bases.append(inner.text.decode())

            # Extract method signatures from body
            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    if child.type in ("method_signature", "property_signature"):
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            methods.append(name_node.text.decode())

            types.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                methods=methods,
                bases=bases,
                decorators=["interface"],
            ))

        if node.type == "enum_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            types.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                decorators=["enum"],
            ))

        if node.type == "abstract_class_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    if child.type == "method_definition":
                        mn = child.child_by_field_name("name")
                        if mn:
                            methods.append(mn.text.decode())
            bases = []
            for child in node.named_children:
                if child.type == "class_heritage":
                    for inner in child.named_children:
                        if inner.type == "identifier":
                            bases.append(inner.text.decode())
            types.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                methods=methods,
                bases=bases,
                decorators=["abstract"],
            ))

        for child in node.named_children:
            self._collect_ts_types(child, types)
