"""
Deterministic rules for detecting logging and metrics gaps.

Each rule function takes indexed facts and returns a list of DetectedProblem.
No LLM is involved — all detection is structural.
"""

from typing import Dict, List

from app.code_parser.schemas import CodeFact

from .schemas import DetectedProblem

# Type aliases for readability
FactsByFile = Dict[str, List[CodeFact]]
FactsByType = Dict[str, List[CodeFact]]


# ========== Helpers ==========


def _facts_in_range(
    facts: List[CodeFact], line_start: int, line_end: int, fact_type: str
) -> List[CodeFact]:
    """Return facts of a given type whose line range overlaps [line_start, line_end]."""
    return [
        f
        for f in facts
        if f.fact_type == fact_type
        and f.line_start >= line_start
        and (f.line_end or f.line_start) <= line_end
    ]


def _has_fact_in_range(
    facts: List[CodeFact], line_start: int, line_end: int, fact_type: str
) -> bool:
    """Check if any fact of the given type exists within the line range."""
    return len(_facts_in_range(facts, line_start, line_end, fact_type)) > 0


def _get_enclosing_function(
    fact: CodeFact, facts_by_file: FactsByFile
) -> CodeFact | None:
    """Find the function that encloses a given fact."""
    file_facts = facts_by_file.get(fact.file_path, [])
    for f in file_facts:
        if (
            f.fact_type == "function"
            and f.line_start <= fact.line_start
            and (f.line_end or f.line_start) >= (fact.line_end or fact.line_start)
        ):
            return f
    return None


# ========== Logging Gap Rules ==========


def rule_silent_exception(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """LOG_001: try/catch or error-handling block without any logging call inside."""
    problems = []
    seen = set()

    for fact in facts_by_type.get("try_except", []):
        file_facts = facts_by_file.get(fact.file_path, [])
        line_start = fact.line_start
        line_end = fact.line_end or fact.line_start

        if _has_fact_in_range(file_facts, line_start, line_end, "logging_call"):
            continue

        func_name = fact.parent_function or "<module>"
        key = (fact.file_path, func_name, line_start)
        if key in seen:
            continue
        seen.add(key)

        problems.append(
            DetectedProblem(
                rule_id="LOG_001",
                problem_type="logging_gap",
                severity="HIGH",
                title=f"Silent error handler in {func_name}",
                category="error_handling",
                affected_files=[fact.file_path],
                affected_functions=[func_name],
                evidence=[
                    {
                        "type": "try_except_without_logging",
                        "file": fact.file_path,
                        "line_start": line_start,
                        "line_end": line_end,
                        "function": func_name,
                    }
                ],
            )
        )

    return problems


def rule_http_handler_no_logging(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """LOG_002: HTTP handler function without any logging call."""
    problems = []

    for handler in facts_by_type.get("http_handler", []):
        # Skip controller class-level markers (only care about functions)
        if handler.metadata.get("kind") == "controller_class":
            continue

        # Find the handler function's range
        func_name = handler.name
        file_facts = facts_by_file.get(handler.file_path, [])

        # Find the matching function definition to get its full range
        func_fact = None
        for f in file_facts:
            if f.fact_type == "function" and f.name == func_name:
                func_fact = f
                break

        if not func_fact:
            continue

        line_start = func_fact.line_start
        line_end = func_fact.line_end or func_fact.line_start

        if _has_fact_in_range(file_facts, line_start, line_end, "logging_call"):
            continue

        problems.append(
            DetectedProblem(
                rule_id="LOG_002",
                problem_type="logging_gap",
                severity="MEDIUM",
                title=f"HTTP handler '{func_name}' has no logging",
                category="observability",
                affected_files=[handler.file_path],
                affected_functions=[func_name],
                evidence=[
                    {
                        "type": "http_handler_no_logging",
                        "file": handler.file_path,
                        "function": func_name,
                        "line_start": line_start,
                        "line_end": line_end,
                    }
                ],
            )
        )

    return problems


def rule_external_io_no_logging(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """LOG_003: External I/O call (DB, HTTP, file) in a function without logging."""
    problems = []
    seen_functions = set()

    for io_fact in facts_by_type.get("external_io", []):
        func = _get_enclosing_function(io_fact, facts_by_file)
        if not func:
            continue

        func_key = (func.file_path, func.name)
        if func_key in seen_functions:
            continue

        file_facts = facts_by_file.get(func.file_path, [])
        line_start = func.line_start
        line_end = func.line_end or func.line_start

        if _has_fact_in_range(file_facts, line_start, line_end, "logging_call"):
            seen_functions.add(func_key)
            continue

        seen_functions.add(func_key)
        problems.append(
            DetectedProblem(
                rule_id="LOG_003",
                problem_type="logging_gap",
                severity="MEDIUM",
                title=f"External I/O in '{func.name}' without logging",
                category="external_calls",
                affected_files=[io_fact.file_path],
                affected_functions=[func.name],
                evidence=[
                    {
                        "type": "external_io_no_logging",
                        "file": io_fact.file_path,
                        "function": func.name,
                        "io_call": io_fact.name,
                        "io_line": io_fact.line_start,
                    }
                ],
            )
        )

    return problems


def rule_error_path_no_error_log(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """LOG_004: Function has try/catch but no error-level logging anywhere inside."""
    problems = []
    seen_functions = set()

    for try_fact in facts_by_type.get("try_except", []):
        func_name = try_fact.parent_function
        if not func_name:
            continue

        func_key = (try_fact.file_path, func_name)
        if func_key in seen_functions:
            continue
        seen_functions.add(func_key)

        # Find the enclosing function
        func = _get_enclosing_function(try_fact, facts_by_file)
        if not func:
            continue

        file_facts = facts_by_file.get(func.file_path, [])
        line_start = func.line_start
        line_end = func.line_end or func.line_start

        # Check if there's any error-level logging in the function
        logging_calls = _facts_in_range(
            file_facts, line_start, line_end, "logging_call"
        )
        has_error_log = any(
            lc.metadata.get("log_level") in ("error", "exception", "critical", "fatal")
            for lc in logging_calls
        )

        if has_error_log:
            continue

        problems.append(
            DetectedProblem(
                rule_id="LOG_004",
                problem_type="logging_gap",
                severity="MEDIUM",
                title=f"Error handler in '{func_name}' lacks error-level logging",
                category="error_handling",
                affected_files=[try_fact.file_path],
                affected_functions=[func_name],
                evidence=[
                    {
                        "type": "try_except_without_error_log",
                        "file": try_fact.file_path,
                        "function": func_name,
                        "try_line": try_fact.line_start,
                    }
                ],
            )
        )

    return problems


def rule_large_function_no_logging(
    facts_by_file: FactsByFile,
    facts_by_type: FactsByType,
    min_lines: int = 50,
) -> List[DetectedProblem]:
    """LOG_005: Large function (>50 lines) with no logging at all."""
    problems = []

    for func in facts_by_type.get("function", []):
        line_start = func.line_start
        line_end = func.line_end or func.line_start
        func_size = line_end - line_start

        if func_size < min_lines:
            continue

        file_facts = facts_by_file.get(func.file_path, [])
        if _has_fact_in_range(file_facts, line_start, line_end, "logging_call"):
            continue

        problems.append(
            DetectedProblem(
                rule_id="LOG_005",
                problem_type="logging_gap",
                severity="LOW",
                title=f"Large function '{func.name}' ({func_size} lines) has no logging",
                category="observability",
                affected_files=[func.file_path],
                affected_functions=[func.name],
                evidence=[
                    {
                        "type": "large_function_no_logging",
                        "file": func.file_path,
                        "function": func.name,
                        "line_count": func_size,
                        "line_start": line_start,
                        "line_end": line_end,
                    }
                ],
            )
        )

    return problems


# ========== Metrics Gap Rules ==========


def rule_http_handler_no_metrics(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """MET_001: HTTP handler exists but no metrics instrumentation in the same file."""
    problems = []
    checked_files = set()

    for handler in facts_by_type.get("http_handler", []):
        if handler.metadata.get("kind") == "controller_class":
            continue

        if handler.file_path in checked_files:
            continue
        checked_files.add(handler.file_path)

        file_facts = facts_by_file.get(handler.file_path, [])
        has_metrics = any(f.fact_type == "metrics_call" for f in file_facts)

        if has_metrics:
            continue

        # Collect all handler names in this file
        handler_names = [
            f.name
            for f in file_facts
            if f.fact_type == "http_handler"
            and f.metadata.get("kind") != "controller_class"
        ]

        problems.append(
            DetectedProblem(
                rule_id="MET_001",
                problem_type="metrics_gap",
                severity="HIGH",
                title=f"HTTP handlers in '{handler.file_path}' have no metrics",
                category="observability",
                affected_files=[handler.file_path],
                affected_functions=handler_names,
                metric_type="histogram",
                suggested_metric_names=[
                    "http_request_duration_seconds",
                    "http_requests_total",
                ],
                evidence=[
                    {
                        "type": "http_handler_no_metrics",
                        "file": handler.file_path,
                        "handlers": handler_names,
                    }
                ],
            )
        )

    return problems


def rule_external_io_no_latency(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """MET_002: External I/O calls without latency/performance metrics."""
    problems = []
    checked_functions = set()

    for io_fact in facts_by_type.get("external_io", []):
        func = _get_enclosing_function(io_fact, facts_by_file)
        if not func:
            continue

        func_key = (func.file_path, func.name)
        if func_key in checked_functions:
            continue
        checked_functions.add(func_key)

        file_facts = facts_by_file.get(func.file_path, [])
        line_start = func.line_start
        line_end = func.line_end or func.line_start

        if _has_fact_in_range(file_facts, line_start, line_end, "metrics_call"):
            continue

        problems.append(
            DetectedProblem(
                rule_id="MET_002",
                problem_type="metrics_gap",
                severity="MEDIUM",
                title=f"External I/O in '{func.name}' has no latency metrics",
                category="performance",
                affected_files=[io_fact.file_path],
                affected_functions=[func.name],
                metric_type="histogram",
                suggested_metric_names=[
                    f"{func.name}_duration_seconds",
                ],
                evidence=[
                    {
                        "type": "external_io_no_latency",
                        "file": io_fact.file_path,
                        "function": func.name,
                        "io_call": io_fact.name,
                    }
                ],
            )
        )

    return problems


def rule_no_business_metrics(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """MET_003: No metrics calls found anywhere in the codebase."""
    metrics_calls = facts_by_type.get("metrics_call", [])
    if len(metrics_calls) > 0:
        return []

    # Only flag if there are actual functions in the codebase
    functions = facts_by_type.get("function", [])
    if len(functions) == 0:
        return []

    all_files = list(facts_by_file.keys())
    return [
        DetectedProblem(
            rule_id="MET_003",
            problem_type="metrics_gap",
            severity="HIGH",
            title="No metrics instrumentation found in the codebase",
            category="observability",
            affected_files=all_files[:10],  # Cap at 10 for readability
            metric_type="counter",
            suggested_metric_names=[
                "requests_total",
                "errors_total",
                "request_duration_seconds",
            ],
            evidence=[
                {
                    "type": "no_metrics_at_all",
                    "total_files": len(all_files),
                    "total_functions": len(functions),
                }
            ],
        )
    ]


def rule_error_no_counter(
    facts_by_file: FactsByFile, facts_by_type: FactsByType
) -> List[DetectedProblem]:
    """MET_004: Error handling blocks without error-count metrics."""
    problems = []
    checked_functions = set()

    for try_fact in facts_by_type.get("try_except", []):
        func_name = try_fact.parent_function
        if not func_name:
            continue

        func_key = (try_fact.file_path, func_name)
        if func_key in checked_functions:
            continue
        checked_functions.add(func_key)

        func = _get_enclosing_function(try_fact, facts_by_file)
        if not func:
            continue

        file_facts = facts_by_file.get(func.file_path, [])
        line_start = func.line_start
        line_end = func.line_end or func.line_start

        if _has_fact_in_range(file_facts, line_start, line_end, "metrics_call"):
            continue

        problems.append(
            DetectedProblem(
                rule_id="MET_004",
                problem_type="metrics_gap",
                severity="LOW",
                title=f"Error handler in '{func_name}' has no error counter",
                category="error_tracking",
                affected_files=[try_fact.file_path],
                affected_functions=[func_name],
                metric_type="counter",
                suggested_metric_names=[f"{func_name}_errors_total"],
                evidence=[
                    {
                        "type": "try_except_no_counter",
                        "file": try_fact.file_path,
                        "function": func_name,
                        "try_line": try_fact.line_start,
                    }
                ],
            )
        )

    return problems
