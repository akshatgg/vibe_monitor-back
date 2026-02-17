"""
Python code parser using Tree-sitter.

Extracts functions, classes, imports, and code facts from Python source code.
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
from .call_patterns import is_external_io, is_http_handler_decorator, is_logging_call, is_metrics_call

logger = logging.getLogger(__name__)


class PythonParser(BaseLanguageParser):
    """Parser for Python source files using Tree-sitter."""

    def __init__(self):
        self._parser = get_parser("python")

    @property
    def language(self) -> str:
        return "python"

    @property
    def extensions(self) -> List[str]:
        return [".py"]

    def parse(self, content: str, file_path: str) -> ParsedFileResult:
        """Parse Python source code into backward-compatible format."""
        try:
            tree = self._parser.parse(content.encode())
            root = tree.root_node

            functions = self._extract_functions(root, content)
            classes = self._extract_classes(root, content)
            imports = self._extract_imports(root, content)
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

    def extract_facts(self, content: str, file_path: str) -> ExtractedFacts:
        """Extract structured code facts for the rule engine."""
        try:
            tree = self._parser.parse(content.encode())
            root = tree.root_node
            facts: List[CodeFact] = []
            self._walk_for_facts(root, facts, file_path)
            return ExtractedFacts(
                file_path=file_path,
                language="python",
                facts=facts,
                line_count=self._count_lines(content),
            )
        except Exception as e:
            return ExtractedFacts(
                file_path=file_path,
                language="python",
                line_count=self._count_lines(content),
                parse_error=f"Python fact extraction error: {str(e)}",
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

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<anonymous>"

            # Check for async
            is_async = any(
                child.type == "async" or (child.type == "" and child.text == b"async")
                for child in node.children
                if not child.is_named
            ) if node.parent and node.parent.type != "decorated_definition" else False

            # Also check text-based detection for async
            node_text_start = node.text.decode()[:20] if node.text else ""
            if node_text_start.startswith("async "):
                is_async = True

            # Get decorators from parent decorated_definition
            decorators = []
            if node.parent and node.parent.type == "decorated_definition":
                decorators = self._get_decorators(node.parent)

            facts.append(CodeFact(
                fact_type="function",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="python",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={
                    "is_async": is_async,
                    "decorators": decorators,
                    "params": self._get_params(node),
                },
            ))

            # Check if this function is an HTTP handler (by decorators)
            for dec in decorators:
                if is_http_handler_decorator("python", dec):
                    facts.append(CodeFact(
                        fact_type="http_handler",
                        name=name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_class=parent_class,
                        metadata={"decorator": dec},
                    ))
                    break

            # Recurse into function body
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=name, parent_class=parent_class)
            return

        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<anonymous>"

            decorators = []
            if node.parent and node.parent.type == "decorated_definition":
                decorators = self._get_decorators(node.parent)

            facts.append(CodeFact(
                fact_type="class",
                name=name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="python",
                parent_function=parent_func,
                parent_class=parent_class,
                metadata={"decorators": decorators},
            ))

            # Recurse into class body
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    self._walk_for_facts(child, facts, file_path, parent_func=parent_func, parent_class=name)
            return

        if node.type == "decorated_definition":
            # Don't emit a fact for decorated_definition itself;
            # the decorators are attached to the inner function/class
            for child in node.named_children:
                if child.type in ("function_definition", "class_definition"):
                    self._walk_for_facts(child, facts, file_path, parent_func, parent_class)
            return

        if node.type == "try_statement":
            facts.append(CodeFact(
                fact_type="try_except",
                name="try",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="python",
                parent_function=parent_func,
                parent_class=parent_class,
            ))
            # Continue walking children
            for child in node.named_children:
                self._walk_for_facts(child, facts, file_path, parent_func, parent_class)
            return

        if node.type == "call":
            obj_name, method_name = self._resolve_call(node)
            if obj_name and method_name:
                if is_logging_call("python", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="logging_call",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_function=parent_func,
                        parent_class=parent_class,
                        metadata={"log_level": method_name},
                    ))
                elif is_metrics_call("python", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="metrics_call",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_external_io("python", obj_name, method_name):
                    facts.append(CodeFact(
                        fact_type="external_io",
                        name=f"{obj_name}.{method_name}",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
            elif method_name:
                # Standalone function call
                if is_logging_call("python", None, method_name):
                    facts.append(CodeFact(
                        fact_type="logging_call",
                        name=method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_function=parent_func,
                        parent_class=parent_class,
                        metadata={"log_level": "info"},
                    ))
                elif is_metrics_call("python", None, method_name):
                    facts.append(CodeFact(
                        fact_type="metrics_call",
                        name=method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))
                elif is_external_io("python", None, method_name):
                    facts.append(CodeFact(
                        fact_type="external_io",
                        name=method_name,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        parent_function=parent_func,
                        parent_class=parent_class,
                    ))

        if node.type in ("import_statement", "import_from_statement"):
            module_name = self._get_import_module(node)
            facts.append(CodeFact(
                fact_type="import",
                name=module_name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="python",
                parent_function=parent_func,
                parent_class=parent_class,
            ))

        # Default: recurse into children
        for child in node.named_children:
            self._walk_for_facts(child, facts, file_path, parent_func, parent_class)

    # ========== Backward-Compatible Extraction ==========

    def _extract_functions(self, root, content: str) -> List[FunctionInfo]:
        """Extract function definitions from the AST."""
        functions = []
        self._collect_functions(root, functions)
        return functions

    def _collect_functions(self, node, functions: List[FunctionInfo]):
        """Recursively collect function definitions."""
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<anonymous>"

            # Check async
            is_async = False
            node_text = node.text.decode()[:20] if node.text else ""
            if node_text.startswith("async "):
                is_async = True

            # Get decorators
            decorators = []
            if node.parent and node.parent.type == "decorated_definition":
                decorators = self._get_decorators(node.parent)

            # Get params
            params = self._get_params(node)

            # Get return type
            return_type = None
            return_type_node = node.child_by_field_name("return_type")
            if return_type_node:
                return_type = return_type_node.text.decode()

            functions.append(FunctionInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                params=params,
                decorators=decorators,
                is_async=is_async,
                return_type=return_type,
            ))

        for child in node.named_children:
            self._collect_functions(child, functions)

    def _extract_classes(self, root, content: str) -> List[ClassInfo]:
        """Extract class definitions from the AST."""
        classes = []
        self._collect_classes(root, classes)
        return classes

    def _collect_classes(self, node, classes: List[ClassInfo]):
        """Recursively collect class definitions."""
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<anonymous>"

            # Get base classes
            bases = []
            superclasses = node.child_by_field_name("superclasses")
            if superclasses:
                for arg in superclasses.named_children:
                    bases.append(arg.text.decode())

            # Get decorators
            decorators = []
            if node.parent and node.parent.type == "decorated_definition":
                decorators = self._get_decorators(node.parent)

            # Get methods
            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.named_children:
                    if child.type == "function_definition":
                        mn = child.child_by_field_name("name")
                        if mn:
                            methods.append(mn.text.decode())
                    elif child.type == "decorated_definition":
                        for inner in child.named_children:
                            if inner.type == "function_definition":
                                mn = inner.child_by_field_name("name")
                                if mn:
                                    methods.append(mn.text.decode())

            classes.append(ClassInfo(
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                methods=methods,
                bases=bases,
                decorators=decorators,
            ))

        for child in node.named_children:
            self._collect_classes(child, classes)

    def _extract_imports(self, root, content: str) -> List[ImportInfo]:
        """Extract import statements from the AST."""
        imports = []
        self._collect_imports(root, imports)
        return imports

    def _collect_imports(self, node, imports: List[ImportInfo]):
        """Recursively collect import statements."""
        if node.type == "import_statement":
            # import x, import x as y
            for child in node.named_children:
                if child.type == "dotted_name":
                    imports.append(ImportInfo(
                        module=child.text.decode(),
                        names=[],
                    ))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node:
                        imports.append(ImportInfo(
                            module=name_node.text.decode(),
                            names=[],
                            alias=alias_node.text.decode() if alias_node else None,
                        ))

        elif node.type == "import_from_statement":
            # from x import y, z
            module_node = node.child_by_field_name("module_name")
            module = module_node.text.decode() if module_node else ""
            is_relative = module.startswith(".")
            names = []
            for child in node.named_children:
                if child.type == "dotted_name" and child != module_node:
                    names.append(child.text.decode())
                elif child.type == "aliased_import":
                    name_n = child.child_by_field_name("name")
                    if name_n:
                        names.append(name_n.text.decode())
                elif child.type == "wildcard_import":
                    names.append("*")
            imports.append(ImportInfo(
                module=module,
                names=names,
                is_relative=is_relative,
            ))

        for child in node.named_children:
            self._collect_imports(child, imports)

    # ========== Helpers ==========

    def _get_decorators(self, decorated_node) -> List[str]:
        """Extract decorator names from a decorated_definition node."""
        decorators = []
        for child in decorated_node.named_children:
            if child.type == "decorator":
                # The decorator content is after the @ symbol
                # Could be identifier, attribute, or call
                for inner in child.named_children:
                    if inner.type == "identifier":
                        decorators.append(inner.text.decode())
                    elif inner.type == "attribute":
                        decorators.append(inner.text.decode())
                    elif inner.type == "call":
                        func = inner.child_by_field_name("function")
                        if func:
                            decorators.append(func.text.decode())
        return decorators

    def _get_params(self, func_node) -> List[str]:
        """Extract parameter names from a function_definition node."""
        params = []
        params_node = func_node.child_by_field_name("parameters")
        if not params_node:
            return params

        for child in params_node.named_children:
            if child.type == "identifier":
                name = child.text.decode()
                if name not in ("self", "cls"):
                    params.append(name)
            elif child.type in ("default_parameter", "typed_parameter", "typed_default_parameter"):
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode()
                    if name not in ("self", "cls"):
                        params.append(name)
            elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                # *args, **kwargs
                for inner in child.named_children:
                    if inner.type == "identifier":
                        params.append(inner.text.decode())
        return params

    def _resolve_call(self, call_node) -> tuple[Optional[str], Optional[str]]:
        """Resolve a call node to (object_name, method_name)."""
        func = call_node.child_by_field_name("function")
        if not func:
            return None, None

        if func.type == "attribute":
            obj = func.child_by_field_name("object")
            attr = func.child_by_field_name("attribute")
            obj_name = obj.text.decode() if obj else None
            method_name = attr.text.decode() if attr else None
            return obj_name, method_name

        if func.type == "identifier":
            return None, func.text.decode()

        return None, None

    def _get_import_module(self, import_node) -> str:
        """Get the module name from an import node."""
        if import_node.type == "import_from_statement":
            module_node = import_node.child_by_field_name("module_name")
            return module_node.text.decode() if module_node else ""
        # import_statement
        for child in import_node.named_children:
            if child.type == "dotted_name":
                return child.text.decode()
            if child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                return name_node.text.decode() if name_node else ""
        return ""
