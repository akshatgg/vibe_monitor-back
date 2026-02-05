import logging

from functools import partial
from langgraph.graph import StateGraph, END
from langchain_core.language_models import BaseChatModel

from .state import RCAState
from .agents import (
    resolve_execution_context_agent,
    classify_query_intent,
    conversational_agent,
    hypothesis_agent,
    evidence_agent,
    validation_agent,
    synthesis_agent,
)

logger = logging.getLogger(__name__)


def _route_after_intent_classification(state: RCAState) -> str:
    """
    Route based on query intent: conversational queries vs RCA investigations.
    """
    intent = state.get("query_intent", "rca_investigation")
    
    # Everything that is NOT explicitly an RCA investigation goes to the conversational agent
    # This matches the "chatbot" persona better and avoids hardcoding a list of conversational intents
    if intent == "rca_investigation":
        return "hypothesize"
    
    return "conversational"


def _route_after_validation(state: RCAState) -> str:
    iteration = int(state.get("iteration") or 0)
    max_loops = state.get("max_loops") or (state.get("context", {}) or {}).get("max_loops") or 2
    max_loops = int(max_loops) if str(max_loops).isdigit() else 2

    hypotheses = state.get("hypotheses") or []
    validated = [
        h
        for h in hypotheses
        if h.get("validation") == "validated"
    ]
    if validated:
        return "synthesize"

    if iteration >= max_loops:
        return "synthesize"

    if hypotheses and all(h.get("validation") == "rejected" for h in hypotheses):
        return "hypothesize"

    return "gather_evidence"


def create_rca_graph(llm: BaseChatModel, db, workspace_id: str, callbacks=None):
    graph = StateGraph(RCAState)

    # Context and routing
    graph.add_node("resolve_context", partial(resolve_execution_context_agent, db=db))
    graph.add_node("classify_intent", partial(classify_query_intent, llm=llm))
    
    # Conversational path
    async def _conversational(state: RCAState) -> RCAState:
        execution_context = state.get("execution_context")
        if execution_context is None:
            state["report"] = "Unable to access workspace context. Please try again."
            return state
        return await conversational_agent(
            state=state,
            llm=llm,
            execution_context=execution_context,
            callbacks=callbacks,
        )
    
    graph.add_node("conversational", _conversational)
    
    # RCA investigation path
    graph.add_node("hypothesize", partial(hypothesis_agent, llm=llm))

    async def _gather_evidence(state: RCAState) -> RCAState:
        execution_context = state.get("execution_context")
        if execution_context is None:
            return state
        return await evidence_agent(
            state=state,
            llm=llm,
            execution_context=execution_context,
            callbacks=callbacks,
        )

    graph.add_node("gather_evidence", _gather_evidence)
    graph.add_node("validate", partial(validation_agent, llm=llm))
    graph.add_node("synthesize", partial(synthesis_agent, llm=llm))

    # Graph flow
    graph.set_entry_point("resolve_context")
    graph.add_edge("resolve_context", "classify_intent")
    graph.add_conditional_edges("classify_intent", _route_after_intent_classification)
    
    # Conversational path ends immediately
    graph.add_edge("conversational", END)
    
    # RCA path continues as before
    graph.add_edge("hypothesize", "gather_evidence")
    graph.add_edge("gather_evidence", "validate")
    graph.add_conditional_edges("validate", _route_after_validation)
    graph.add_edge("synthesize", END)

    return graph.compile()
