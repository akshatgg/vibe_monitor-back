from typing import Any, Dict, List, Optional, TypedDict


class Hypothesis(TypedDict):
    hypothesis: str
    evidence: Dict[str, Any]
    validation: str
    confidence: Optional[int]
    rationale: Optional[str]
    next_steps: Optional[List[str]]

class RCAState(TypedDict):
    task: str
    workspace_id: str
    context: Dict[str, Any]

    query_intent: Optional[str]
    failing_service: Optional[str]
    timeframe: Optional[str]
    severity: Optional[str]
    environment_name: Optional[str]

    hypotheses: List[Hypothesis]

    root_cause: Optional[str]
    report: Optional[str]

    trace: List[Dict[str, Any]]
    history: List[Dict[str, Any]]

    error: Optional[str]

    iteration: Optional[int]
    max_loops: Optional[int]
    execution_context: Optional[Any]
    evidence_board: Optional[Dict[str, Any]]
