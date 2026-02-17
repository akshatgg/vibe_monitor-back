"""
JavaScript code parser using Tree-sitter.

Extracts functions, classes, imports, and code facts from JavaScript source code.
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
    is_http_handler_registration,
    is_logging_call,
    is_metrics_call,
)

logger = logging.getLogger(__name__)


class JavaScriptParser(BaseLanguageParser):
    """Parser for JavaScript source files using Tree-sitter."""

    def __init__(self):
        self._parser = get_parser("javascript")

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def extensions(self) -> List[str]:
        return [".js", ".jsx", ".mjs", ".cjs"]

    def _get_ts_parser(self):
        """Get the Tree-sitter parser. Override in subclasses for different languages."""
        return self._parser

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse JavaScript source code into backward-compatible format."""
        try:
            tree = self._get_ts_parser().parse(content.encode())
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
                parse_error=f"JavaScript parse error: {str(e)}",
            )

    def extract_facts(self, content: str, file_path: str) -> ExtractedFacts:
        """Extract structured code facts for the rule engine."""
        try:
            tree = self._get_ts_parser().parse(content.encode())
            root = tree.root_node
            facts: List[CodeFact] = []
            self._walk_for_facts(root, facts, file_path)
            return ExtractedFacts(
                file_path=file_path,
                language=self.language,
                facts=facts,
                line_count=self._count_lines(content),
            )
        except Exception as e:
            return ExtractedFacts(
                file_path=file_path,
                language=self.language,
                line_count=self._count_lines(content),
                parse_error=f"{self.language} fact extraction error: {str(e)}",
            )

    # ========== Fact Extraction (Tree Walking) ==========

    def _walk_for_facts(
        self,
        node,
        facts: List[CodeFact],
        file_path: str,
        parent_func: Optional[str] = None,
        parent_class: Optional[str] = None,
    ):
        """Recursively walk the AST to extract code facts."""
        lang = self.language

        # Function declaration: function foo() {}
        if node.type == "function_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            is_async = self._has_keyword_child(node, "async")
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"is_async": is_async, "params": self._get_js_params(node)},
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
            return

        # Generator function declaration
        if node.type == "generator_function_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"is_generator": True, "params": self._get_js_params(node)},
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
            return

        # Variable declarator with arrow function or function expression
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value and value.type in ("arrow_function", "function_expression", "function"):
                name = self._get_field_text(node, "name") or "<anonymous>"
                is_async = self._has_keyword_child(value, "async")
                facts.append(CodeFact(
                    fact_type="function",
                    name=name,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language=lang,
                    parent_function=parent_func,
                    parent_class=parent_class,
                    metadata={"is_async": is_async, "is_arrow": value.type == "arrow_function"},
                ))
                body = value.child_by_field_name("body")
                if body:
                    for child in body.named_children:
                        self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
                return

        # Method definition inside class
        if node.type == "method_definition":
            name = self._get_field_text(node, "name") or "<anonymous>"
            is_async = self._has_keyword_child(node, "async")
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"is_async": is_async, "is_method": True},
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
            return

        # Class declaration
        if node.type in ("class_declaration", "class"):
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
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=parent_func, parent_class=name)
            return

        # Try statement
        if node.type == "try_statement":
            facts.append(CodeFact(
                fact_type="try_except",
                name="try",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
            ))
            for child in node.named_children:
                self._walk_for_facts(child, facts, file_path, parent_func, parent_class)
            return

        # Call expression
        if node.type == "call_expression":
            obj_name, method_name = self._resolve_js_call(node)
            if obj_name and method_name:
                if is_logging_call(lang, obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="logging_call",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language=lang,
                        parent_function=parent_func,
                        parent_class=parent_class,
                        metadata={"log_level": method_name},
                    ))
                elif is_metrics_call(lang, obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="metrics_call",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language=lang,
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_external_io(lang, obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="external_io",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language=lang,
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_http_handler_registration(lang, obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="http_handler",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language=lang,
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
            elif method_name:
                if is_logging_call(lang, None, method_name):
                    facts.append(CodeFact(
                        fact_type="logging_call",
                        name=method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language=lang,
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_external_io(lang, None, method_name):
                    facts.append(CodeFact(
                        fact_type="external_io",
                        name=method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language=lang,
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))

        # Import statement
        if node.type == "import_statement":
            source = node.child_by_field_name("source")
            module = self._strip_quotes(source.text.decode()) if source else ""
            facts.append(CodeFact(
                fact_type="import",
                name=module,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=lang,
                parent_function=parent_func,
                parent_class=parent_class,
            ))

        # Default: recurse into children
        for child in node.named_children:
            self._walk_for_facts(child, facts, file_path, parent_func, parent_class)

    # ========== Backward-Compatible Extraction ==========

    def _extract_functions(self, root) -> List[FunctionInfo]:
        """Extract function definitions from the AST."""
        functions = []
        self._collect_functions(root, functions, set())
        return functions

    def _collect_functions(self, node, functions: List[FunctionInfo], seen: set):
        """Recursively collect function definitions."""
        if node.type == "function_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            if name not in seen:
                seen.add(name)
                is_async = self._has_keyword_child(node, "async")
                functions.append(FunctionInfo(
                    name=name,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    params=self._get_js_params(node),
                    is_async=is_async,
                ))

        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value and value.type in ("arrow_function", "function_expression", "function"):
                name = self._get_field_text(node, "name") or "<anonymous>"
                if name not in seen:
                    seen.add(name)
                    is_async = self._has_keyword_child(value, "async")
                    functions.append(FunctionInfo(
                        name=name,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        params=self._get_js_params(value),
                        is_async=is_async,
                    ))

        for child in node.named_children:
            self._collect_functions(child, functions, seen)

    def _extract_classes(self, root) -> List[ClassInfo]:
        """Extract class definitions from the AST."""
        classes = []
        self._collect_classes(root, classes)
        return classes

    def _collect_classes(self, node, classes: List[ClassInfo]):
        """Recursively collect class definitions."""
        if node.type in ("class_declaration", "class"):
            name = self._get_field_text(node, "name") or "<anonymous>"
            bases = []
            for child in node.named_children:
                if child.type == "class_heritage":
                    for inner in child.named_children:
                        if inner.type == "identifier":
                            bases.append(inner.text.decode())

            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    if child.type == "method_definition":
                        mn = child.child_by_field_name("name")
                        if mn:
                            methods.append(mn.text.decode())

            classes.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                methods=methods,
                bases=bases,
            ))

        for child in node.named_children:
            self._collect_classes(child, classes)

    def _extract_imports(self, root) -> List[ImportInfo]:
        """Extract import statements from the AST."""
        imports = []
        self._collect_imports(root, imports)
        return imports

    def _collect_imports(self, node, imports: List[ImportInfo]):
        """Recursively collect import statements."""
        if node.type == "import_statement":
            source = node.child_by_field_name("source")
            module = self._strip_quotes(source.text.decode()) if source else ""
            names = []

            for child in node.named_children:
                if child.type == "import_clause":
                    for inner in child.named_children:
                        if inner.type == "identifier":
                            names.append(inner.text.decode())
                        elif inner.type == "named_imports":
                            for spec in inner.named_children:
                                if spec.type == "import_specifier":
                                    name_n = spec.child_by_field_name("name")
                                    if name_n:
                                        names.append(name_n.text.decode())
                        elif inner.type == "namespace_import":
                            for ns_child in inner.named_children:
                                if ns_child.type == "identifier":
                                    names.append(f"* as {ns_child.text.decode()}")

            imports.append(ImportInfo(
                module=module,
                names=names,
                is_relative=module.startswith("."),
            ))

        # CommonJS require
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func and func.type == "identifier" and func.text == b"require":
                args = node.child_by_field_name("arguments")
                if args and args.named_child_count > 0:
                    first_arg = args.named_children[0]
                    if first_arg.type == "string":
                        module = self._strip_quotes(first_arg.text.decode())
                        # Get the variable name from parent
                        names = []
                        parent = node.parent
                        if parent and parent.type == "variable_declarator":
                            name_node = parent.child_by_field_name("name")
                            if name_node:
                                if name_node.type == "identifier":
                                    names.append(name_node.text.decode())
                                elif name_node.type == "object_pattern":
                                    for prop in name_node.named_children:
                                        if prop.type == "shorthand_property_identifier_pattern":
                                            names.append(prop.text.decode())
                        imports.append(ImportInfo(
                            module=module,
                            names=names,
                            is_relative=module.startswith("."),
                        ))

        for child in node.named_children:
            self._collect_imports(child, imports)

    # ========== Helpers ==========

    def _get_field_text(self, node, field: str) -> Optional[str]:
        """Get text of a named field child."""
        child = node.child_by_field_name(field)
        return child.text.decode() if child else None

    def _has_keyword_child(self, node, keyword: str) -> bool:
        """Check if a node has a keyword token child."""
        keyword_bytes = keyword.encode()
        for child in node.children:
            if not child.is_named and child.text == keyword_bytes:
                return True
        return False

    def _get_js_params(self, node) -> List[str]:
        """Extract parameter names from a function node."""
        params = []
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            # Arrow functions may use 'parameter' field
            params_node = node.child_by_field_name("parameter")
            if params_node and params_node.type == "identifier":
                return [params_node.text.decode()]
            return params

        for child in params_node.named_children:
            if child.type == "identifier":
                params.append(child.text.decode())
            elif child.type == "assignment_pattern":
                left = child.child_by_field_name("left")
                if left and left.type == "identifier":
                    params.append(left.text.decode())
            elif child.type == "rest_pattern":
                for inner in child.named_children:
                    if inner.type == "identifier":
                        params.append(inner.text.decode())
        return params

    def _resolve_js_call(self, call_node) -> tuple[Optional[str], Optional[str]]:
        """Resolve a call_expression to (object_name, method_name)."""
        func = call_node.child_by_field_name("function")
        if not func:
            return None, None

        if func.type == "member_expression":
            obj = func.child_by_field_name("object")
            prop = func.child_by_field_name("property")
            obj_name = obj.text.decode() if obj and obj.type == "identifier" else None
            method_name = prop.text.decode() if prop else None
            return obj_name, method_name

        if func.type == "identifier":
            return None, func.text.decode()

        return None, None

    def _strip_quotes(self, s: str) -> str:
        """Remove surrounding quotes from a string literal."""
        if len(s) >= 2 and s[0] in ("'", '"', '`') and s[-1] in ("'", '"', '`'):
            return s[1:-1]
        return s
