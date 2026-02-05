import json
import logging
import re

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Maximum code size to parse (1 MB). Larger inputs are rejected to prevent DoS.
MAX_CODE_SIZE = 1_000_000

# Workaround for tree-sitter-languages bug with Python 3.12
TREE_SITTER_AVAILABLE = False
get_parser = None
_TREE_SITTER_ERROR = None

try:
    from tree_sitter_languages import get_parser as _get_parser_tsl

    _test_parser = _get_parser_tsl("python")
    TREE_SITTER_AVAILABLE = True
    get_parser = _get_parser_tsl
except Exception as e:
    get_parser = None
    _TREE_SITTER_ERROR = (
        "tree-sitter-languages unavailable or incompatible with current Python runtime: "
        + str(e)
    )


@tool
async def parse_code_tool(code: str, language: str = "python") -> str:
    """
    Parse code using tree-sitter to extract AST structure and detect syntax errors.

    Args:
        code: The source code to parse
        language: Programming language (python, javascript, typescript, go, java, ruby, php)

    Returns:
        JSON string with language, has_error flag, and AST sexp representation
    """
    return json.dumps(parse_code(code=code, language=language), indent=2)


def parse_code(code: str, language: str = "python") -> dict:
    if len(code) > MAX_CODE_SIZE:
        logger.warning(
            f"Code size ({len(code)} bytes) exceeds limit ({MAX_CODE_SIZE}), "
            "returning findings only"
        )
        return {
            "language": language,
            "has_error": True,
            "parser": "skipped",
            "error": f"Code too large ({len(code)} bytes, max {MAX_CODE_SIZE})",
            "code_length": len(code),
            "line_count": len(code.splitlines()),
            "findings": _find_interesting_lines(code[:MAX_CODE_SIZE]),
        }
    if language == "python":
        return _parse_python(code)
    return _parse_with_tree_sitter_or_fallback(code=code, language=language)


_INTERESTING_LINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
        "stacktrace",
    ),
    (
        re.compile(
            r"\b(logger|log|console)\.(exception|error|warn|warning|critical)\b"
        ),
        "log",
    ),
    (re.compile(r"\braise\s+\w+|\bthrow\s+new\b|\bpanic\s*\(", re.IGNORECASE), "raise"),
    (
        re.compile(
            r"\bHTTPException\b|\bstatus_code\s*=\s*(4\d\d|5\d\d)\b|\bHTTP/\d\.\d\b",
            re.IGNORECASE,
        ),
        "http_error",
    ),
    (
        re.compile(
            r"\brate\s*limit\b|\bthrottl(e|ing)\b|\btoo many requests\b|\b429\b",
            re.IGNORECASE,
        ),
        "rate_limit",
    ),
    (re.compile(r"\btimeout\b|\bdeadline\b|\bETIMEDOUT\b", re.IGNORECASE), "timeout"),
    (
        re.compile(
            r"\bretry\b|\bbackoff\b|\bexponential\b|\btenacity\b", re.IGNORECASE
        ),
        "retry",
    ),
    (
        re.compile(r"\bcircuit\s*breaker\b|\bbreaker\b|\btrip(ped)?\b", re.IGNORECASE),
        "circuit_breaker",
    ),
    (
        re.compile(
            r"\bunauthorized\b|\bforbidden\b|\bpermission\b|\bauth(orization)?\b",
            re.IGNORECASE,
        ),
        "auth",
    ),
    (
        re.compile(r"\bdeadlock\b|\bpool\b.*\b(exhaust|full)\b", re.IGNORECASE),
        "db_pool",
    ),
    (
        re.compile(
            r"\bconnection\b.*\b(refused|reset)\b|\bECONNRESET\b|\bECONNREFUSED\b",
            re.IGNORECASE,
        ),
        "network",
    ),
    (re.compile(r"\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bJOIN\b"), "sql"),
    (
        re.compile(
            r"\bhttpx\b|\brequests\b|\baxios\b|\bfetch\s*\(",
            re.IGNORECASE,
        ),
        "http_client",
    ),
    (
        re.compile(
            r"\bgrpc\b|\bkafka\b|\brabbitmq\b|\bsqs\b|\bpubsub\b",
            re.IGNORECASE,
        ),
        "messaging",
    ),
    (re.compile(r"\bos\.environ\b|\bgetenv\s*\(", re.IGNORECASE), "env"),
    (
        re.compile(
            r"\bfeature[_-]?flag\b|\btoggle\b|\bexperiment\b|\benable(d)?\b.*\bflag\b",
            re.IGNORECASE,
        ),
        "feature_flag",
    ),
    (
        re.compile(
            r"\b(alembic|migration)\b",
            re.IGNORECASE,
        ),
        "migration",
    ),
    (
        re.compile(
            r"\b(sentry|prometheus|opentelemetry|otel|trace(id)?|span)\b",
            re.IGNORECASE,
        ),
        "observability",
    ),
    (re.compile(r"\b(time\.sleep|asyncio\.sleep)\s*\(", re.IGNORECASE), "sleep"),
    (
        re.compile(
            r"\b(delay|latency|slow|performance|perf)\b",
            re.IGNORECASE,
        ),
        "performance",
    ),
    (re.compile(r"\b(SIMULATED|MOCK|FAKE|STUB)_[A-Z0-9_]+\b"), "simulation"),
    (re.compile(r"\bTODO\b|\bFIXME\b|\bHACK\b"), "todo"),
]


def find_interesting_lines(code: str) -> list[dict]:
    return _find_interesting_lines(code)


def _find_interesting_lines(code: str) -> list[dict]:
    hits: list[dict] = []
    for idx, line in enumerate(code.splitlines(), 1):
        for pattern, kind in _INTERESTING_LINE_PATTERNS:
            if pattern.search(line):
                hits.append(
                    {
                        "type": kind,
                        "line": idx,
                        "text": line.strip()[:300],
                    }
                )
                if len(hits) >= 60:
                    return hits
                break
    return hits


def _parse_python(code: str) -> dict:
    try:
        import ast
        import re

        try:
            tree = ast.parse(code)
            functions = []
            classes = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_info = {
                        "name": node.name,
                        "line": node.lineno,
                        "type": "function",
                    }
                    if (
                        node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)
                    ):
                        func_info["docstring"] = node.body[0].value.value[:200]
                    functions.append(func_info)
                elif isinstance(node, ast.ClassDef):
                    class_info = {
                        "name": node.name,
                        "line": node.lineno,
                        "type": "class",
                    }
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            methods.append({"name": item.name, "line": item.lineno})
                    if methods:
                        class_info["methods"] = methods
                    classes.append(class_info)

            if not functions and not classes:
                func_pattern = r"^\s*(?:async\s+)?def\s+(\w+)\s*\([^)]*\)\s*:"
                class_pattern = r"^\s*class\s+(\w+)"
                lines = code.split("\n")
                for i, line in enumerate(lines, 1):
                    func_match = re.match(func_pattern, line)
                    if func_match:
                        functions.append(
                            {"name": func_match.group(1), "line": i, "type": "function"}
                        )
                    class_match = re.match(class_pattern, line)
                    if class_match:
                        classes.append(
                            {"name": class_match.group(1), "line": i, "type": "class"}
                        )

            return {
                "language": "python",
                "has_error": False,
                "parser": "python_ast",
                "functions": functions,
                "classes": classes,
                "function_count": len(functions),
                "class_count": len(classes),
                "findings": _find_interesting_lines(code),
            }
        except SyntaxError as e:
            func_pattern = r"^\s*(?:async\s+)?def\s+(\w+)\s*\([^)]*\)\s*:"
            class_pattern = r"^\s*class\s+(\w+)"
            lines = code.split("\n")
            functions = []
            classes = []
            for i, line in enumerate(lines, 1):
                func_match = re.match(func_pattern, line)
                if func_match:
                    functions.append(
                        {"name": func_match.group(1), "line": i, "type": "function"}
                    )
                class_match = re.match(class_pattern, line)
                if class_match:
                    classes.append(
                        {"name": class_match.group(1), "line": i, "type": "class"}
                    )

            return {
                "language": "python",
                "has_error": True,
                "parser": "python_ast_regex_fallback",
                "error": str(e),
                "error_line": getattr(e, "lineno", None),
                "functions": functions,
                "classes": classes,
                "function_count": len(functions),
                "class_count": len(classes),
                "note": "Extracted functions using regex due to syntax error",
                "findings": _find_interesting_lines(code),
            }
    except ImportError:
        return _parse_with_tree_sitter_or_fallback(code=code, language="python")


def _parse_with_tree_sitter_or_fallback(code: str, language: str) -> dict:
    if get_parser is not None:
        try:
            parser = get_parser(language)
            tree = parser.parse(bytes(code, "utf8"))
            root = tree.root_node
            return {
                "language": language,
                "has_error": bool(getattr(root, "has_error", False)),
                "parser": "tree_sitter",
                "sexp": root.sexp()[:2000],
                "findings": _find_interesting_lines(code),
            }
        except Exception as e:
            error_msg = f"tree-sitter parsing failed: {str(e)}"
    else:
        error_msg = getattr(
            globals(),
            "_TREE_SITTER_ERROR",
            "tree-sitter-languages package not available",
        )

    return {
        "language": language,
        "has_error": True,
        "parser": "fallback",
        "error": error_msg,
        "code_length": len(code),
        "line_count": len(code.splitlines()),
        "findings": _find_interesting_lines(code),
    }
