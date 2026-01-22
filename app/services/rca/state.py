"""
State schema for LangGraph RCA Agent V2
"""

from typing import TypedDict, Optional, Dict, Any, List


class RCAStateV2(TypedDict):
    """
    State for RCA investigation flow.
    Tracks investigation progress through nodes.
    """
    
    # ============================================================================
    # Input (from user)
    # ============================================================================
    user_query: str
    workspace_id: str
    context: Dict[str, Any]  # workspace context (service_repo_mapping, etc)
    files: Optional[List[Dict[str, Any]]]  # Optional files (images, videos) for multimodal analysis
    
    # ============================================================================
    # Router (from ROUTER node) - NEW
    # ============================================================================
    query_type: Optional[str]  # "casual" or "incident" - determines which path to take
    
    # ============================================================================
    # Parsed Query (from PARSE node)
    # ============================================================================
    primary_service: Optional[str]  # Main service mentioned by user
    symptoms: List[str]  # List of symptoms (errors, slowness, etc)
    incident_type: Optional[str]  # "availability", "performance", or "data"
    
    # ============================================================================
    # Investigation Plan (from PLAN node)
    # ============================================================================
    services_to_check: List[str]  # Services to investigate
    tools_to_use: List[str]  # Tool categories: "logs", "metrics", "code", "commits"
    
    # ============================================================================
    # Evidence (from INVESTIGATE node) - SUMMARIZED, not raw
    # ============================================================================
    logs_summary: Dict[str, str]  # {service: summary_text}
    metrics_summary: Dict[str, Any]  # {service: {metric: value}}
    code_findings: Dict[str, str]  # {service: code_summary}
    commit_findings: Dict[str, Any]  # {service: commits_list}
    
    # ============================================================================
    # NEW: Iterative Investigation (from ITERATIVE_INVESTIGATE node)
    # ============================================================================
    investigation_chain: Optional[List[Dict[str, Any]]]  # List of {service, findings, depth, decision}
    final_decision: Optional[str]  # ROOT_CAUSE_FOUND | MAX_DEPTH_REACHED | INCONCLUSIVE
    
    # ============================================================================
    # Root Cause (from ANALYZE_AND_TRACE node)
    # ============================================================================
    root_cause: Optional[str]  # Description of root cause
    root_service: Optional[str]  # Service where root cause is
    root_commit: Optional[str]  # Commit ID if applicable
    confidence: Optional[float]  # Confidence score 0-1
    
    # NEW: Multi-level RCA fields
    victim_service: Optional[str]  # Service where user saw the issue (first in chain)
    intermediate_services: Optional[List[str]]  # Services in between victim and root
    
    # ============================================================================
    # Output (from GENERATE node)
    # ============================================================================
    final_report: Optional[str]  # Final formatted report
    
    # ============================================================================
    # Control Flow
    # ============================================================================
    iteration: int  # Current iteration number
    max_iterations: int  # Max allowed iterations
    
    # ============================================================================
    # Error Handling
    # ============================================================================
    error: Optional[str]  # Error message if something fails
    
    # ============================================================================
    # Debug/Tracking
    # ============================================================================
    intermediate_steps: List[Dict[str, Any]]  # Track each step for debugging
