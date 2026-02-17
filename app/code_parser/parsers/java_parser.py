"""
Java code parser using Tree-sitter.

Extracts methods, classes, interfaces, enums, imports, and code facts from Java source code.
"""

import logging
from typing import List, Optional

from tree_sitter_language_pack import get_parser

from ..schemas import (
    ClassInfo,
    CodeFact,
    ExtractedFacts,
    FunctionInfo,
    ImportInfo,
    ParsedFileResult,
)
from .base import BaseLanguageParser
from .call_patterns import (
    is_external_io,
    is_http_handler_decorator,
    is_logging_call,
    is_metrics_call,
)

logger = logging.getLogger(__name__)


class JavaParser(BaseLanguageParser):
    """Parser for Java source files using Tree-sitter."""

    def __init__(self):
        self._parser = get_parser("java")

    @property
    def language(self) -> str:
        return "java"

    @property
    def extensions(self) -> List[str]:
        return [".java"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse Java source code into backward-compatible format."""
        try:
            tree = self._parser.parse(content.encode())
            root = tree.root_node

            functions = self._extract_functions(root)
            classes = self._extract_classes(root)
            imports = self._extract_imports(root)
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

    def extract_facts(self, content: str, file_path: str) -> ExtractedFacts:
        """Extract structured code facts for the rule engine."""
        try:
            tree = self._parser.parse(content.encode())
            root = tree.root_node
            facts: List[CodeFact] = []
            self._walk_for_facts(root, facts, file_path)
            return ExtractedFacts(
                file_path=file_path,
                language="java",
                facts=facts,
                line_count=self._count_lines(content),
            )
        except Exception as e:
            return ExtractedFacts(
                file_path=file_path,
                language="java",
                line_count=self._count_lines(content),
                parse_error=f"Java fact extraction error: {str(e)}",
            )

    # ========== Fact Extraction ==========

    def _walk_for_facts(
        self,
        node,
        facts: List[CodeFact],
        file_path: str,
        parent_func: Optional[str] = None,
        parent_class: Optional[str] = None,
    ):
        """Recursively walk the AST to extract code facts."""

        # Class declaration
        if node.type == "class_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            annotations = self._get_annotations(node)
            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "class", "annotations": annotations},
            ))
            # Check for HTTP handler annotations on the class (e.g., @RestController)
            for ann in annotations:
                if ann in ("RestController", "Controller"):
                    facts.append(CodeFact(
                        fact_type="http_handler",
                        name=name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="java",
                        parent_class=parent_class,
                        metadata={"kind": "controller_class"},
                    ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=parent_func, parent_class=name)
            return

        # Interface declaration
        if node.type == "interface_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "interface"},
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=parent_func, parent_class=name)
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
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"kind": "enum"},
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=parent_func, parent_class=name)
            return

        # Method declaration
        if node.type == "method_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            annotations = self._get_annotations(node)
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={
                    "params": self._get_java_params(node),
                    "return_type": self._get_field_text(node, "type"),
                    "annotations": annotations,
                },
            ))
            # Check for HTTP handler annotations
            for ann in annotations:
                if is_http_handler_decorator("java", ann):
                    facts.append(CodeFact(
                        fact_type="http_handler",
                        name=name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="java",
                        parent_class=parent_class,
                        metadata={"annotation": ann},
                    ))
                    break
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
            return

        # Constructor declaration
        if node.type == "constructor_declaration":
            name = self._get_field_text(node, "name") or "<constructor>"
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={
                    "params": self._get_java_params(node),
                    "is_constructor": True,
                },
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
            return

        # Try-catch statement
        if node.type == "try_statement":
            facts.append(CodeFact(
                fact_type="try_except",
                name="try_catch",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
            ))

        # Try-with-resources statement
        if node.type == "try_with_resources_statement":
            facts.append(CodeFact(
                fact_type="try_except",
                name="try_with_resources",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                parent_function=parent_func,
                parent_class=parent_class,
            ))

        # Method invocation (call expression)
        if node.type == "method_invocation":
            obj_name, method_name = self._resolve_java_call(node)
            if method_name:
                if is_logging_call("java", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="logging_call",
                        name=f"{obj_name}.{method_name}" if obj_name else method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="java",
                        parent_function=parent_func,
                        parent_class=parent_class,
                        metadata={"log_level": method_name.lower()},
                    ))
                elif is_metrics_call("java", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="metrics_call",
                        name=f"{obj_name}.{method_name}" if obj_name else method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="java",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_external_io("java", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="external_io",
                        name=f"{obj_name}.{method_name}" if obj_name else method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="java",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))

        # Import declaration
        if node.type == "import_declaration":
            module = self._get_import_path(node)
            if module:
                is_static = any(
                    child.type == "static" or (hasattr(child, "text") and child.text == b"static")
                    for child in node.children
                )
                facts.append(CodeFact(
                    fact_type="import",
                    name=module,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="java",
                    metadata={"is_static": is_static},
                ))

        # Default: recurse
        for child in node.named_children:
            self._walk_for_facts(child, facts, file_path, parent_func, parent_class)

    # ========== Backward-Compatible Extraction ==========

    def _extract_functions(self, root) -> List[FunctionInfo]:
        """Extract method and constructor declarations."""
        functions = []
        self._collect_functions(root, functions)
        return functions

    def _collect_functions(self, node, functions: List[FunctionInfo], class_name: Optional[str] = None):
        if node.type == "method_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            params = self._get_java_params(node)
            return_type = self._get_field_text(node, "type")
            annotations = self._get_annotations(node)
            is_async = return_type and "CompletableFuture" in return_type

            functions.append(FunctionInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                params=params,
                return_type=return_type,
                decorators=annotations,
                is_async=is_async,
            ))

        elif node.type == "constructor_declaration":
            name = self._get_field_text(node, "name") or "<constructor>"
            params = self._get_java_params(node)
            functions.append(FunctionInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                params=params,
                decorators=self._get_annotations(node),
            ))

        elif node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            cn = self._get_field_text(node, "name")
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._collect_functions(child, functions, class_name=cn)
            return

        for child in node.named_children:
            self._collect_functions(child, functions, class_name)

    def _extract_classes(self, root) -> List[ClassInfo]:
        """Extract class, interface, and enum declarations."""
        classes = []
        self._collect_classes(root, classes)
        return classes

    def _collect_classes(self, node, classes: List[ClassInfo]):
        if node.type == "class_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            bases = self._get_class_bases(node)
            annotations = self._get_annotations(node)
            methods = self._get_method_names_from_body(node)

            classes.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                methods=methods,
                bases=bases,
                decorators=annotations,
            ))

        elif node.type == "interface_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            bases = self._get_interface_extends(node)
            annotations = self._get_annotations(node)
            methods = self._get_method_names_from_body(node)

            classes.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                methods=methods,
                bases=bases,
                decorators=annotations + ["interface"],
            ))

        elif node.type == "enum_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            annotations = self._get_annotations(node)

            classes.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                decorators=annotations + ["enum"],
            ))

        for child in node.named_children:
            self._collect_classes(child, classes)

    def _extract_imports(self, root) -> List[ImportInfo]:
        """Extract import declarations."""
        imports = []
        self._collect_imports(root, imports)
        return imports

    def _collect_imports(self, node, imports: List[ImportInfo]):
        if node.type == "import_declaration":
            module = self._get_import_path(node)
            if module:
                is_static = any(
                    child.type == "static" or (hasattr(child, "text") and child.text == b"static")
                    for child in node.children
                )
                parts = module.split(".")
                names = [parts[-1]] if parts else []
                imports.append(ImportInfo(
                    module=module,
                    names=names,
                    alias="static" if is_static else None,
                ))

        for child in node.named_children:
            self._collect_imports(child, imports)

    # ========== Helpers ==========

    def _get_field_text(self, node, field: str) -> Optional[str]:
        child = node.child_by_field_name(field)
        return child.text.decode() if child else None

    def _get_java_params(self, node) -> List[str]:
        """Extract parameter names from a method/constructor."""
        params = []
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            return params
        for child in params_node.named_children:
            if child.type == "formal_parameter" or child.type == "spread_parameter":
                name_node = child.child_by_field_name("name")
                if name_node:
                    params.append(name_node.text.decode())
        return params

    def _get_annotations(self, node) -> List[str]:
        """Extract annotation names from a node's children (siblings before the declaration)."""
        annotations = []
        # In Java tree-sitter, annotations are children with type "marker_annotation" or "annotation"
        for child in node.children:
            if child.type == "marker_annotation":
                name_node = child.child_by_field_name("name")
                if name_node:
                    annotations.append(name_node.text.decode())
            elif child.type == "annotation":
                name_node = child.child_by_field_name("name")
                if name_node:
                    annotations.append(name_node.text.decode())
            elif child.type == "modifiers":
                for mod_child in child.named_children:
                    if mod_child.type in ("marker_annotation", "annotation"):
                        name_node = mod_child.child_by_field_name("name")
                        if name_node:
                            annotations.append(name_node.text.decode())
        return annotations

    def _get_class_bases(self, node) -> List[str]:
        """Extract superclass and implemented interfaces."""
        bases = []
        superclass = node.child_by_field_name("superclass")
        if superclass:
            # superclass node contains the type
            for child in superclass.named_children:
                bases.append(child.text.decode())
        interfaces = node.child_by_field_name("interfaces")
        if interfaces:
            # interfaces node: type_list containing types
            for child in interfaces.named_children:
                if child.type == "type_list":
                    for inner in child.named_children:
                        bases.append(inner.text.decode())
                else:
                    bases.append(child.text.decode())
        return bases

    def _get_interface_extends(self, node) -> List[str]:
        """Extract extended interfaces."""
        bases = []
        extends = node.child_by_field_name("extends_interfaces")
        if extends:
            for child in extends.named_children:
                if child.type == "type_list":
                    for inner in child.named_children:
                        bases.append(inner.text.decode())
                else:
                    bases.append(child.text.decode())
        return bases

    def _get_method_names_from_body(self, node) -> List[str]:
        """Get method names from a class/interface body."""
        methods = []
        body = node.child_by_field_name("body")
        if not body:
            return methods
        for child in body.named_children:
            if child.type in ("method_declaration", "constructor_declaration"):
                name = self._get_field_text(child, "name")
                if name:
                    methods.append(name)
        return methods

    def _get_import_path(self, node) -> Optional[str]:
        """Extract the full import path from an import_declaration node."""
        # In Java tree-sitter, the import path can be a scoped_identifier or identifier
        for child in node.named_children:
            if child.type in ("scoped_identifier", "identifier"):
                return child.text.decode()
            elif child.type == "asterisk":
                # Wildcard import: already captured by scoped_identifier parent
                continue
        return None

    def _resolve_java_call(self, call_node) -> tuple[Optional[str], Optional[str]]:
        """Resolve a method_invocation to (object_name, method_name)."""
        name_node = call_node.child_by_field_name("name")
        method_name = name_node.text.decode() if name_node else None

        obj_node = call_node.child_by_field_name("object")
        if obj_node:
            # Could be chained: System.out.println -> obj=System.out, method=println
            # For pattern matching we take the last identifier before the method
            if obj_node.type == "field_access":
                field = obj_node.child_by_field_name("field")
                obj_name = field.text.decode() if field else obj_node.text.decode()
            elif obj_node.type == "identifier":
                obj_name = obj_node.text.decode()
            else:
                obj_name = obj_node.text.decode()
            return obj_name, method_name

        return None, method_name
