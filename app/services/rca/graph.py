"""
Graph construction for LangGraph RCA Agent V2.
Defines the investigation flow through nodes.

REDESIGNED ARCHITECTURE:
- Dual path: casual queries → conversational node, incidents → structured investigation
- Router decides which path to take
- More flexible and robust
"""

import logging
from typing import Dict, Any, Literal
from functools import partial

from langgraph.graph import StateGraph, END
from langchain_core.language_models import BaseChatModel

from .state import RCAStateV2
from .nodes import (
    router_node,
    conversational_node,
    parse_query_node,
    iterative_investigate_node,  # Iterative multi-level investigation
    analyze_and_trace_node,
    generate_report_node,
)

logger = logging.getLogger(__name__)


def _route_after_router(state: RCAStateV2) -> Literal["conversational", "parse"]:
    """
    Route based on query type:
    - casual → conversational node
    - incident → parse node (structured investigation)
    """
    query_type = state.get("query_type", "incident")
    
    if query_type == "casual":
        logger.info("Routing to conversational node (casual query)")
        return "conversational"
    else:
        logger.info("Routing to parse node (incident investigation)")
        return "parse"


def create_rca_graph(llm: BaseChatModel, tools_dict: Dict[str, Any]):
    """
    Create the RCA investigation graph with dual paths.
    
    Flow:
        START → Router
                  ↓ (casual)         ↓ (incident)
              Conversational   Parse → Iterative_Investigate → Analyze → Generate
                  ↓                        ↓
                END                      END
    
    NEW: Uses iterative_investigate_node for multi-level upstream tracing
    
    Args:
        llm: Language model
        tools_dict: Dictionary of available tools {tool_name: tool}
    
    Returns:
        Compiled graph
    """
    logger.info("Creating redesigned RCA graph with iterative investigation")
    
    # Initialize graph
    graph = StateGraph(RCAStateV2)
    
    # ========================================================================
    # Add nodes with bound parameters
    # ========================================================================
    
    # Node 0: Router (decides casual vs incident)
    graph.add_node(
        "router",
        partial(router_node, llm=llm)
    )
    
    # Node 0.5: Conversational (handles casual queries)
    graph.add_node(
        "conversational",
        partial(conversational_node, llm=llm, tools_dict=tools_dict)
    )
    
    # Node 1: Parse query (for incidents only)
    graph.add_node(
        "parse",
        partial(parse_query_node, llm=llm)
    )
    
    # Node 3: Iterative multi-level investigation
    graph.add_node(
        "iterative_investigate",
        partial(iterative_investigate_node, tools_dict=tools_dict, llm=llm)
    )
    
    # Node 4: Analyze and trace root cause
    graph.add_node(
        "analyze_trace",
        partial(analyze_and_trace_node, llm=llm)
    )
    
    # Node 5: Generate report
    graph.add_node(
        "generate",
        partial(generate_report_node, llm=llm)
    )
    
    # ========================================================================
    # Define edges with conditional routing
    # ========================================================================
    
    # Set entry point
    graph.set_entry_point("router")
    
    # Conditional routing from router
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            "conversational": "conversational",  # Casual queries
            "parse": "parse",                     # Incidents
        }
    )
    
    # Conversational path (direct to END)
    graph.add_edge("conversational", END)
    
    # NEW: Incident investigation path (using iterative investigation)
    # Skip plan node - go directly from parse to iterative_investigate
    graph.add_edge("parse", "iterative_investigate")
    graph.add_edge("iterative_investigate", "analyze_trace")
    graph.add_edge("analyze_trace", "generate")
    graph.add_edge("generate", END)
    
    # OLD: Comment out old flow (kept for reference)
    # graph.add_edge("parse", "plan")
    # graph.add_edge("plan", "investigate")
    # graph.add_edge("investigate", "analyze_trace")
    
    # ========================================================================
    # Compile graph
    # ========================================================================
    
    compiled_graph = graph.compile()
    
    logger.info("RCA graph created successfully:")
    logger.info("  Casual path: router → conversational → END")
    logger.info("  Incident path: router → parse → iterative_investigate → analyze → generate → END")
    
    return compiled_graph




