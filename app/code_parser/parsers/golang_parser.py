"""
Go code parser using Tree-sitter.

Extracts functions, structs, interfaces, imports, and code facts from Go source code.
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


class GolangParser(BaseLanguageParser):
    """Parser for Go source files using Tree-sitter."""

    def __init__(self):
        self._parser = get_parser("go")

    @property
    def language(self) -> str:
        return "go"

    @property
    def extensions(self) -> List[str]:
        return [".go"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse Go source code into backward-compatible format."""
        try:
            tree = self._parser.parse(content.encode())
            root = tree.root_node

            functions = self._extract_functions(root)
            classes = self._extract_types(root)
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
                parse_error=f"Go parse error: {str(e)}",
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
                language="go",
                facts=facts,
                line_count=self._count_lines(content),
            )
        except Exception as e:
            return ExtractedFacts(
                file_path=file_path,
                language="go",
                line_count=self._count_lines(content),
                parse_error=f"Go fact extraction error: {str(e)}",
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

        # Function declaration
        if node.type == "function_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="go",
                parent_function=parent_func,
                metadata={
                    "params": self._get_go_params(node),
                    "return_type": self._get_go_return_type(node),
                },
            ))
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name)
            return

        # Method declaration (has receiver)
        if node.type == "method_declaration":
            name = self._get_field_text(node, "name") or "<anonymous>"
            receiver_type = self._get_receiver_type(node)
            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="go",
                parent_function=parent_func,
                parent_class=receiver_type,
                metadata={
                    "receiver_type": receiver_type,
                    "is_method": True,
                    "params": self._get_go_params(node),
                },
            ))

            # Check if this is an HTTP handler by parameter types
            if self._is_go_http_handler(node):
                facts.append(CodeFact(
                    fact_type="http_handler",
                    name=name,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="go",
                    parent_class=receiver_type,
                    metadata={"receiver_type": receiver_type},
                ))

            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=receiver_type)
            return

        # Type declaration (struct, interface)
        if node.type == "type_declaration":
            for child in node.named_children:
                if child.type == "type_spec":
                    name = self._get_field_text(child, "name") or "<anonymous>"
                    type_node = child.child_by_field_name("type")
                    if type_node:
                        kind = "struct" if type_node.type == "struct_type" else (
                            "interface" if type_node.type == "interface_type" else "type_alias"
                        )
                        facts.append(CodeFact(
                            fact_type="class",
                            name=name,
                            file_path=file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            language="go",
                            parent_function=parent_func,
                            metadata={"kind": kind},
                        ))

        # If statement (for Go error handling: if err != nil)
        if node.type == "if_statement":
            if self._is_error_check(node):
                facts.append(CodeFact(
                    fact_type="try_except",
                    name="if_err",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="go",
                    parent_function=parent_func,
                    parent_class=parent_class,
                ))

        # Defer statement
        if node.type == "defer_statement":
            facts.append(CodeFact(
                fact_type="defer",
                name="defer",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="go",
                parent_function=parent_func,
                parent_class=parent_class,
            ))

        # Call expression
        if node.type == "call_expression":
            obj_name, method_name = self._resolve_go_call(node)
            if obj_name and method_name:
                if is_logging_call("go", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="logging_call",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="go",
                        parent_function=parent_func,
                        parent_class=parent_class,
                        metadata={"log_level": method_name.lower()},
                    ))
                elif is_metrics_call("go", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="metrics_call",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="go",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_external_io("go", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="external_io",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="go",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_http_handler_registration("go", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="http_handler",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="go",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))

        # Import declaration
        if node.type == "import_declaration":
            for child in node.named_children:
                if child.type == "import_spec":
                    path_node = child.child_by_field_name("path")
                    if path_node:
                        module = self._strip_quotes(path_node.text.decode())
                        facts.append(CodeFact(
                            fact_type="import",
                            name=module,
                            file_path=file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            language="go",
                            parent_function=parent_func,
                        ))
                elif child.type == "import_spec_list":
                    for spec in child.named_children:
                        if spec.type == "import_spec":
                            path_node = spec.child_by_field_name("path")
                            if path_node:
                                module = self._strip_quotes(path_node.text.decode())
                                facts.append(CodeFact(
                                    fact_type="import",
                                    name=module,
                                    file_path=file_path,
                                    line_start=spec.start_point[0] + 1,
                                    line_end=spec.end_point[0] + 1,
                                    language="go",
                                    parent_function=parent_func,
                                ))
                elif child.type == "interpreted_string_literal":
                    module = self._strip_quotes(child.text.decode())
                    facts.append(CodeFact(
                        fact_type="import",
                        name=module,
                        file_path=file_path,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        language="go",
                        parent_function=parent_func,
                    ))

        # Default: recurse
        for child in node.named_children:
            self._walk_for_facts(child, facts, file_path, parent_func, parent_class)

    # ========== Backward-Compatible Extraction ==========

    def _extract_functions(self, root) -> List[FunctionInfo]:
        """Extract function and method declarations."""
        functions = []
        self._collect_functions(root, functions)
        return functions

    def _collect_functions(self, node, functions: List[FunctionInfo]):
        if node.type in ("function_declaration", "method_declaration"):
            name = self._get_field_text(node, "name") or "<anonymous>"
            params = self._get_go_params(node)
            return_type = self._get_go_return_type(node)
            decorators = []
            if node.type == "method_declaration":
                receiver_type = self._get_receiver_type(node)
                if receiver_type:
                    decorators.append(f"method:{receiver_type}")

            functions.append(FunctionInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                params=params,
                return_type=return_type,
                decorators=decorators,
            ))

        for child in node.named_children:
            self._collect_functions(child, functions)

    def _extract_types(self, root) -> List[ClassInfo]:
        """Extract struct and interface definitions."""
        types = []
        self._collect_types(root, types)
        return types

    def _collect_types(self, node, types: List[ClassInfo]):
        if node.type == "type_declaration":
            for child in node.named_children:
                if child.type == "type_spec":
                    name = self._get_field_text(child, "name") or "<anonymous>"
                    type_node = child.child_by_field_name("type")
                    if type_node and type_node.type == "struct_type":
                        types.append(ClassInfo(
                            name=name,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            decorators=["struct"],
                        ))
                    elif type_node and type_node.type == "interface_type":
                        methods = self._get_interface_methods(type_node)
                        types.append(ClassInfo(
                            name=name,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            methods=methods,
                            decorators=["interface"],
                        ))

        for child in node.named_children:
            self._collect_types(child, types)

    def _extract_imports(self, root) -> List[ImportInfo]:
        """Extract import declarations."""
        imports = []
        self._collect_imports(root, imports)
        return imports

    def _collect_imports(self, node, imports: List[ImportInfo]):
        if node.type == "import_declaration":
            for child in node.named_children:
                if child.type == "import_spec":
                    self._add_import_spec(child, imports)
                elif child.type == "import_spec_list":
                    for spec in child.named_children:
                        if spec.type == "import_spec":
                            self._add_import_spec(spec, imports)
                elif child.type == "interpreted_string_literal":
                    module = self._strip_quotes(child.text.decode())
                    imports.append(ImportInfo(
                        module=module,
                        names=[module.split("/")[-1]],
                    ))

        for child in node.named_children:
            self._collect_imports(child, imports)

    def _add_import_spec(self, spec_node, imports: List[ImportInfo]):
        path_node = spec_node.child_by_field_name("path")
        if not path_node:
            return
        module = self._strip_quotes(path_node.text.decode())
        alias_node = spec_node.child_by_field_name("name")
        alias = None
        if alias_node:
            alias_text = alias_node.text.decode()
            alias = alias_text if alias_text != "_" else None
        imports.append(ImportInfo(
            module=module,
            names=[module.split("/")[-1]],
            alias=alias,
        ))

    # ========== Helpers ==========

    def _get_field_text(self, node, field: str) -> Optional[str]:
        child = node.child_by_field_name(field)
        return child.text.decode() if child else None

    def _get_go_params(self, node) -> List[str]:
        """Extract parameter names from a function/method."""
        params = []
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            return params
        for child in params_node.named_children:
            if child.type == "parameter_declaration":
                for inner in child.named_children:
                    if inner.type == "identifier":
                        params.append(inner.text.decode())
        return params

    def _get_go_return_type(self, node) -> Optional[str]:
        """Extract return type from a function."""
        result = node.child_by_field_name("result")
        if result:
            return result.text.decode()
        return None

    def _get_receiver_type(self, node) -> Optional[str]:
        """Extract receiver type from a method declaration."""
        receiver = node.child_by_field_name("receiver")
        if not receiver:
            return None
        # Get the type from receiver parameter list
        text = receiver.text.decode()
        # Clean up: (r *Receiver) -> Receiver
        text = text.strip("()")
        parts = text.split()
        if parts:
            return parts[-1].strip("*")
        return None

    def _get_interface_methods(self, interface_node) -> List[str]:
        """Extract method names from an interface_type node."""
        methods = []
        for child in interface_node.named_children:
            if child.type == "method_spec":
                name_node = child.child_by_field_name("name")
                if name_node:
                    methods.append(name_node.text.decode())
        return methods

    def _is_error_check(self, if_node) -> bool:
        """Check if an if_statement is a Go error check (if err != nil)."""
        condition = if_node.child_by_field_name("condition")
        if not condition:
            return False
        text = condition.text.decode()
        return "err" in text and "nil" in text

    def _is_go_http_handler(self, node) -> bool:
        """Check if a function/method matches Go HTTP handler signature."""
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            return False
        text = params_node.text.decode()
        return "http.ResponseWriter" in text and "http.Request" in text

    def _resolve_go_call(self, call_node) -> tuple[Optional[str], Optional[str]]:
        """Resolve a call_expression to (object_name, method_name)."""
        func = call_node.child_by_field_name("function")
        if not func:
            return None, None

        if func.type == "selector_expression":
            operand = func.child_by_field_name("operand")
            field = func.child_by_field_name("field")
            obj_name = operand.text.decode() if operand and operand.type == "identifier" else None
            method_name = field.text.decode() if field else None
            return obj_name, method_name

        if func.type == "identifier":
            return None, func.text.decode()

        return None, None

    def _strip_quotes(self, s: str) -> str:
        if len(s) >= 2 and s[0] in ('"', '`') and s[-1] in ('"', '`'):
            return s[1:-1]
        return s
