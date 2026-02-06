"""
ReAct Agent for Health Review analysis.

Implements a ReAct (Reason + Act) pattern using LangGraph:
1. Analyze codebase structure
2. Cross-reference with logs and metrics
3. Identify observability gaps
4. Generate recommendations
"""

import json
import logging
import re
from typing import Any, Annotated, Dict, List, Optional, Sequence, TypedDict

from langchain.globals import set_verbose

from app.services.rca.langfuse_handler import get_langfuse_callback

from app.core.config import settings


from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.health_review_system.codebase_sync.schemas import ParsedCodebaseInfo
from app.health_review_system.data_collector.schemas import CollectedData
from app.health_review_system.llm_analyzer.prompts import (
    REACT_SYSTEM_PROMPT,
    INITIAL_ANALYSIS_PROMPT,
    format_errors_for_prompt,
    format_metrics_summary,
)
from app.health_review_system.llm_analyzer.providers import (
    BaseLLMProvider,
    get_default_provider,
)
from app.health_review_system.llm_analyzer.schemas import (
    AnalysisResult,
    AnalyzedError,
    LoggingGap,
    MetricsGap,
)
from app.health_review_system.llm_analyzer.tools.base import (
    AnalysisContext,
    get_all_tools,
    set_analysis_context,
    reset_analysis_context,
)
from app.models import Service

logger = logging.getLogger(__name__)

# Maximum number of agent iterations to prevent infinite loops
MAX_ITERATIONS = 100


class AgentState(TypedDict):
    """State for the ReAct agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    iteration: int
    context: Dict[str, Any]  # Holds service info, codebase summary, etc.


class HealthAnalysisAgent:
    """
    ReAct-based agent for health analysis.

    Uses LangGraph to implement a reasoning loop that:
    1. Reasons about what to investigate
    2. Uses tools to gather information
    3. Analyzes findings to detect gaps
    4. Generates summary and recommendations
    """

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        """
        Initialize the health analysis agent.

        Args:
            provider: LLM provider to use. If None, uses default provider.
        """
        self.provider = provider
        self._graph = None
        self._tools = None
        self._llm_with_tools = None

    def _get_provider(self) -> BaseLLMProvider:
        """Get the LLM provider, initializing if needed."""
        if self.provider is None:
            self.provider = get_default_provider()
        return self.provider

    def _get_tools(self) -> List:
        """Get all available tools."""
        if self._tools is None:
            self._tools = get_all_tools()
        return self._tools

    def _get_llm_with_tools(self):
        """Get LLM bound with tools."""
        if self._llm_with_tools is None:
            provider = self._get_provider()
            llm = provider.get_llm()
            tools = self._get_tools()
            self._llm_with_tools = llm.bind_tools(tools)
        return self._llm_with_tools

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state graph."""
        graph = StateGraph(AgentState)

        # Add nodes
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", ToolNode(self._get_tools()))

        # Add edges
        graph.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END,
            }
        )
        graph.add_edge("tools", "agent")

        # Set entry point
        graph.set_entry_point("agent")

        return graph

    @property
    def graph(self):
        """Get or build the compiled graph."""
        if self._graph is None:
            # Set recursion limit higher than MAX_ITERATIONS * 2 to allow for tool calls
            self._graph = self._build_graph().compile()
        return self._graph

    def _get_config(self):
        """Get config for graph invocation."""
        return {"recursion_limit": MAX_ITERATIONS * 3 + 10}  # Allow enough room for tool calls

    async def _agent_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Agent reasoning node.

        Takes the current state and decides what to do next.
        """
        messages = state["messages"]
        iteration = state.get("iteration", 0)

        logger.debug(f"[Agent] Iteration {iteration}/{MAX_ITERATIONS}, messages so far: {len(messages)}")

        # Check iteration limit
        if iteration >= MAX_ITERATIONS:
            logger.warning(f"Agent reached max iterations ({MAX_ITERATIONS})")
            # Force completion by returning a message without tool calls
            return {
                "messages": [AIMessage(content="Analysis complete. Generating final output based on gathered information.")],
                "iteration": iteration + 1,
            }

        # Call LLM with tools
        llm_with_tools = self._get_llm_with_tools()

        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            error_str = str(e)
            logger.error(f"[Agent] Iteration {iteration}: LLM call failed: {error_str}")

            # If the LLM hallucinated a tool name, return a message telling it to use valid tools
            if "tool_use_failed" in error_str or "not in request.tools" in error_str:
                valid_tools = [t.name for t in self._get_tools()]
                recovery_msg = (
                    f"Error: You tried to call a tool that does not exist. "
                    f"Only use these tools: {valid_tools}"
                )
                logger.warning("[Agent] Recovering from hallucinated tool call, nudging LLM")
                return {
                    "messages": [AIMessage(content=recovery_msg)],
                    "iteration": iteration + 1,
                }
            raise

        # Log what the LLM decided to do
        if isinstance(response, AIMessage):
            if response.tool_calls:
                tool_names = [tc["name"] for tc in response.tool_calls]
                logger.info(f"[Agent] Iteration {iteration}: LLM called tools: {tool_names}")
            else:
                content_preview = (response.content[:200] + "...") if len(response.content) > 200 else response.content
                logger.info(f"[Agent] Iteration {iteration}: LLM responded with text (no tool calls): {content_preview}")
        else:
            logger.warning(f"[Agent] Iteration {iteration}: Unexpected response type: {type(response)}")

        return {
            "messages": [response],
            "iteration": iteration + 1,
        }

    def _should_continue(self, state: AgentState) -> str:
        """Determine if agent should continue or end."""
        messages = state["messages"]
        iteration = state.get("iteration", 0)

        # Check iteration limit
        if iteration >= MAX_ITERATIONS:
            logger.debug(f"[ShouldContinue] Ending: hit max iterations ({MAX_ITERATIONS})")
            return "end"

        # Check if last message has tool calls
        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            if last_message.tool_calls:
                tool_names = [tc["name"] for tc in last_message.tool_calls]
                logger.debug(f"[ShouldContinue] Continuing: tool calls pending: {tool_names}")
                return "continue"
            else:
                logger.debug("[ShouldContinue] Ending: no tool calls in last AIMessage")
        else:
            logger.debug(f"[ShouldContinue] Ending: last message is {type(last_message).__name__}, not AIMessage")

        return "end"

    async def analyze(
        self,
        codebase: Optional[ParsedCodebaseInfo],
        collected_data: Optional[CollectedData],
        service: Service,
    ) -> AnalysisResult:
        """
        Run the full analysis pipeline.

        Args:
            codebase: Parsed codebase information
            collected_data: Collected logs, metrics, and errors
            service: Service model

        Returns:
            AnalysisResult with gaps, analyzed errors, and summary
        """
        if settings.ENVIRONMENT != "prod":
            set_verbose(True)
            logger.debug("set_verbose = True for local development")

        logger.info(f"Starting ReAct analysis for service: {service.name}")

        # Log what data the LLM will have access to
        if collected_data:
            metrics = collected_data.metrics
            if metrics:
                logger.info(
                    f"[Agent] Metrics passed to LLM: "
                    f"latency_p50={metrics.latency_p50}, latency_p99={metrics.latency_p99}, "
                    f"error_rate={metrics.error_rate}, availability={metrics.availability}, "
                    f"throughput={metrics.throughput_per_minute}"
                )
            else:
                logger.warning("[Agent] No metrics data passed to LLM (metrics=None)")
            logger.info(
                f"[Agent] Logs passed: {collected_data.log_count}, "
                f"Errors passed: {len(collected_data.errors) if collected_data.errors else 0}"
            )
        else:
            logger.warning("[Agent] No collected_data passed to LLM")

        if codebase:
            logger.info(
                f"[Agent] Codebase passed: {codebase.total_files} files, "
                f"{codebase.total_functions} functions, {codebase.total_classes} classes"
            )
        else:
            logger.warning("[Agent] No codebase data passed to LLM")

        # Set up analysis context for tools
        context = AnalysisContext(
            codebase=codebase,
            collected_data=collected_data,
            service_name=service.name,
            repository_name=service.repository_name or "unknown",
        )
        token = set_analysis_context(context)

        try:
            # Prepare initial prompt
            initial_prompt = self._build_initial_prompt(codebase, collected_data, service)

            # Build initial state
            initial_state: AgentState = {
                "messages": [
                    SystemMessage(content=REACT_SYSTEM_PROMPT),
                    HumanMessage(content=initial_prompt),
                ],
                "iteration": 0,
                "context": {
                    "service_name": service.name,
                    "repository_name": service.repository_name,
                },
            }

            # Set up Langfuse tracing
            config = self._get_config()
            langfuse_callback = get_langfuse_callback(
                session_id=str(service.id),
                metadata={
                    "service_name": service.name,
                    "repository_name": service.repository_name,
                    "agent_version": "health-review-react",
                },
                tags=["health-review", "langgraph"],
            )
            if langfuse_callback:
                config["callbacks"] = [langfuse_callback]
                logger.info("Langfuse callback added for health review tracing")

            # Log tools bound to the LLM
            tools = self._get_tools()
            logger.info(f"[Agent] Tools bound to LLM: {[t.name for t in tools]}")
            logger.debug(f"[Agent] Initial prompt length: {len(initial_prompt)} chars")

            # Run the agent graph with config
            final_state = await self.graph.ainvoke(initial_state, config=config)

            # Log final state summary
            total_messages = len(final_state.get("messages", []))
            final_iteration = final_state.get("iteration", 0)
            ai_messages = [m for m in final_state.get("messages", []) if isinstance(m, AIMessage)]
            tool_call_count = sum(len(m.tool_calls) for m in ai_messages if m.tool_calls)
            logger.info(
                f"[Agent] Graph complete: {final_iteration} iterations, "
                f"{total_messages} messages, {tool_call_count} tool calls made"
            )

            # Parse results from agent messages
            result = self._parse_results(final_state, codebase, collected_data)

            logger.info(
                f"[Agent] Parsed results: "
                f"logging_gaps={len(result.logging_gaps)}, "
                f"metrics_gaps={len(result.metrics_gaps)}, "
                f"analyzed_errors={len(result.analyzed_errors)}, "
                f"summary_length={len(result.summary)}"
            )

            return result

        except Exception as e:
            logger.exception(f"Error in ReAct analysis: {e}")
            # Return minimal result on error
            return AnalysisResult(
                logging_gaps=[],
                metrics_gaps=[],
                analyzed_errors=[],
                summary=f"Analysis encountered an error: {str(e)}",
                recommendations="Please review the service manually.",
            )

        finally:
            # Clean up context
            reset_analysis_context(token)

    def _build_initial_prompt(
        self,
        codebase: Optional[ParsedCodebaseInfo],
        collected_data: Optional[CollectedData],
        service: Service,
    ) -> str:
        """Build the initial analysis prompt."""
        # Codebase summary
        if codebase:
            total_files = codebase.total_files or 0
            total_functions = codebase.total_functions or 0
            total_classes = codebase.total_classes or 0
            languages = json.dumps(codebase.languages) if codebase.languages else "{}"
        else:
            total_files = 0
            total_functions = 0
            total_classes = 0
            languages = "{}"

        # Collected data summary
        if collected_data:
            log_count = collected_data.log_count or 0
            error_count = len(collected_data.errors) if collected_data.errors else 0
            has_metrics = "Yes" if collected_data.metrics else "No"
            metrics_summary = format_metrics_summary(collected_data.metrics)
            error_summary = format_errors_for_prompt(collected_data.errors) if collected_data.errors else "No errors"
        else:
            log_count = 0
            error_count = 0
            has_metrics = "No"
            metrics_summary = "No metrics available"
            error_summary = "No errors"

        return INITIAL_ANALYSIS_PROMPT.format(
            service_name=service.name,
            repository_name=service.repository_name or "unknown",
            total_files=total_files,
            total_functions=total_functions,
            total_classes=total_classes,
            languages=languages,
            log_count=log_count,
            error_count=error_count,
            has_metrics=has_metrics,
            metrics_summary=metrics_summary,
            error_summary=error_summary,
        )

    def _parse_results(
        self,
        final_state: AgentState,
        codebase: Optional[ParsedCodebaseInfo],
        collected_data: Optional[CollectedData],
    ) -> AnalysisResult:
        """Parse the agent's messages to extract analysis results."""
        messages = final_state["messages"]

        # Collect all AI responses (excluding tool responses)
        ai_responses = []
        for msg in messages:
            if isinstance(msg, AIMessage) and msg.content:
                ai_responses.append(msg.content)

        # Get the last substantive response
        full_response = "\n\n".join(ai_responses[-3:]) if ai_responses else ""

        logger.debug(
            f"[Parser] Parsing from {len(ai_responses)} AI responses, "
            f"combined last 3 length: {len(full_response)} chars"
        )
        if full_response:
            logger.debug(f"[Parser] Response preview (last 500 chars): ...{full_response[-500:]}")

        # Try to extract structured data from responses
        logging_gaps = self._extract_logging_gaps(full_response, messages)
        metrics_gaps = self._extract_metrics_gaps(full_response, messages)
        analyzed_errors = self._extract_analyzed_errors(full_response, collected_data)
        summary, recommendations = self._extract_summary(full_response)

        logger.info(
            f"ReAct analysis complete: {len(logging_gaps)} logging gaps, "
            f"{len(metrics_gaps)} metrics gaps, {len(analyzed_errors)} errors"
        )

        return AnalysisResult(
            logging_gaps=logging_gaps,
            metrics_gaps=metrics_gaps,
            analyzed_errors=analyzed_errors,
            summary=summary,
            recommendations=recommendations,
        )

    def _extract_logging_gaps(
        self,
        response: str,
        messages: Sequence[BaseMessage],
    ) -> List[LoggingGap]:
        """Extract logging gaps from agent response."""
        gaps = []

        # Try to find JSON in response
        try:
            json_match = self._find_json_in_text(response, "logging_gaps")
            if json_match:
                for gap_data in json_match:
                    gaps.append(LoggingGap(
                        description=gap_data.get("description", "Logging gap detected"),
                        category=gap_data.get("category", "general"),
                        priority=gap_data.get("priority", "MEDIUM"),
                        affected_files=gap_data.get("affected_files", []),
                        affected_functions=gap_data.get("affected_functions", []),
                        suggested_log_statement=gap_data.get("suggested_log_statement"),
                        rationale=gap_data.get("rationale"),
                    ))
        except Exception as e:
            logger.debug(f"Could not parse logging gaps JSON: {e}")

        # If no JSON found, try to extract from natural language
        if not gaps:
            gaps = self._extract_gaps_from_text(response, "logging")

        return gaps

    def _extract_metrics_gaps(
        self,
        response: str,
        messages: Sequence[BaseMessage],
    ) -> List[MetricsGap]:
        """Extract metrics gaps from agent response."""
        gaps = []

        # Try to find JSON in response
        try:
            json_match = self._find_json_in_text(response, "metrics_gaps")
            if json_match:
                for gap_data in json_match:
                    gaps.append(MetricsGap(
                        description=gap_data.get("description", "Metrics gap detected"),
                        category=gap_data.get("category", "performance"),
                        metric_type=gap_data.get("metric_type", "gauge"),
                        priority=gap_data.get("priority", "MEDIUM"),
                        affected_components=gap_data.get("affected_components", []),
                        suggested_metric_names=gap_data.get("suggested_metric_names", []),
                        implementation_guide=gap_data.get("implementation_guide"),
                    ))
        except Exception as e:
            logger.debug(f"Could not parse metrics gaps JSON: {e}")

        # If no JSON found, try to extract from natural language
        if not gaps:
            gaps = self._extract_metrics_gaps_from_text(response)

        return gaps

    def _extract_analyzed_errors(
        self,
        response: str,
        collected_data: Optional[CollectedData],
    ) -> List[AnalyzedError]:
        """Extract analyzed errors from agent response."""
        errors = []

        # Start with collected errors and enrich with analysis
        if collected_data and collected_data.errors:
            for error in collected_data.errors:
                # Try to find analysis for this error in response
                likely_cause = self._find_error_analysis(response, error.error_type)

                errors.append(AnalyzedError(
                    error_type=error.error_type,
                    fingerprint=error.fingerprint,
                    count=error.count,
                    severity="HIGH" if error.count > 100 else "MEDIUM",
                    likely_cause=likely_cause or f"Requires investigation: {error.message_sample[:100] if error.message_sample else 'No message'}",
                    code_location=None,  # Would need code parsing to determine
                ))

        return errors[:10]  # Limit to top 10 errors

    def _extract_summary(self, response: str) -> tuple[str, str]:
        """Extract summary and recommendations from response."""
        # Try to find JSON
        try:
            json_match = self._find_json_in_text(response, "summary")
            if json_match and isinstance(json_match, str):
                # Found summary as string
                summary = json_match
                recommendations = self._find_json_in_text(response, "recommendations") or ""
                if isinstance(recommendations, list):
                    recommendations = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations))
                return summary, recommendations
        except Exception:
            pass

        # Fall back to extracting from text
        summary = "Service health analysis completed."
        recommendations = ""

        # Look for summary-like text
        if "summary" in response.lower():
            lines = response.split("\n")
            for i, line in enumerate(lines):
                if "summary" in line.lower() and i + 1 < len(lines):
                    summary = lines[i + 1].strip()
                    break

        # Look for recommendations
        if "recommendation" in response.lower():
            rec_lines = []
            capturing = False
            for line in response.split("\n"):
                if "recommendation" in line.lower():
                    capturing = True
                    continue
                if capturing:
                    if line.strip().startswith(("1.", "2.", "3.", "-", "*")):
                        rec_lines.append(line.strip())
                    elif rec_lines and not line.strip():
                        break
            recommendations = "\n".join(rec_lines)

        # Default summary if nothing found
        if summary == "Service health analysis completed.":
            # Generate based on what we know
            summary = "Analysis completed using ReAct agent. Review the identified gaps and recommendations."

        return summary, recommendations

    def _find_json_in_text(self, text: str, key: Optional[str] = None) -> Any:
        """Find and parse JSON from text, handling nested objects."""

        # Strategy 1: Extract from ```json code blocks
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        code_blocks = re.findall(code_block_pattern, text)
        for block in code_blocks:
            block = block.strip()
            if not block.startswith('{'):
                continue
            try:
                data = json.loads(block)
                if key:
                    if key in data:
                        logger.debug(f"[Parser] Found key '{key}' in ```json code block")
                        return data[key]
                else:
                    return data
            except json.JSONDecodeError:
                # Code block might be truncated, try balanced extraction from it
                inner_candidates = self._extract_balanced_json(block)
                for candidate in inner_candidates:
                    try:
                        data = json.loads(candidate)
                        if key and key in data:
                            logger.debug(f"[Parser] Found key '{key}' in partial ```json code block")
                            return data[key]
                        elif not key:
                            return data
                    except json.JSONDecodeError:
                        continue

        # Strategy 2: Balanced brace matching — find outermost JSON objects
        json_candidates = self._extract_balanced_json(text)
        for candidate in json_candidates:
            try:
                data = json.loads(candidate)
                if key:
                    if key in data:
                        logger.debug(f"[Parser] Found key '{key}' via balanced brace matching")
                        return data[key]
                else:
                    return data
            except json.JSONDecodeError:
                continue

        # Strategy 3: Try to find JSON array
        array_candidates = self._extract_balanced_json(text, open_char='[', close_char=']')
        for candidate in array_candidates:
            try:
                data = json.loads(candidate)
                return data
            except json.JSONDecodeError:
                continue

        logger.debug(f"[Parser] No valid JSON found for key '{key}' in text ({len(text)} chars)")
        return None

    def _extract_balanced_json(self, text: str, open_char: str = '{', close_char: str = '}') -> List[str]:
        """Extract substrings with balanced braces/brackets from text."""
        candidates = []
        i = 0
        while i < len(text):
            if text[i] == open_char:
                depth = 0
                start = i
                in_string = False
                escape_next = False
                j = i
                while j < len(text):
                    ch = text[j]
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                    if ch == '\\' and in_string:
                        escape_next = True
                        j += 1
                        continue
                    if ch == '"' and not escape_next:
                        in_string = not in_string
                    elif not in_string:
                        if ch == open_char:
                            depth += 1
                        elif ch == close_char:
                            depth -= 1
                            if depth == 0:
                                candidates.append(text[start:j + 1])
                                break
                    j += 1
            i += 1
        return candidates

    def _extract_gaps_from_text(self, text: str, gap_type: str) -> List[LoggingGap]:
        """Extract gaps from natural language text."""
        gaps = []

        # Simple pattern matching for common gap descriptions
        patterns = [
            (r"missing (?:error )?logging (?:in|for) ([^.]+)", "error_handling", "HIGH"),
            (r"no (?:error )?logging (?:in|for) ([^.]+)", "error_handling", "HIGH"),
            (r"should add logging (?:to|in) ([^.]+)", "general", "MEDIUM"),
            (r"lacks? audit logging", "security", "MEDIUM"),
        ]

        for pattern, category, priority in patterns:
            matches = re.findall(pattern, text.lower())
            for match in matches:
                gaps.append(LoggingGap(
                    description=f"Missing {gap_type} in {match}",
                    category=category,
                    priority=priority,
                    affected_files=[],
                    affected_functions=[],
                    rationale=f"Detected from analysis: {match}",
                ))

        return gaps[:5]  # Limit to 5 gaps

    def _extract_metrics_gaps_from_text(self, text: str) -> List[MetricsGap]:
        """Extract metrics gaps from natural language text."""
        gaps = []

        patterns = [
            (r"missing (?:latency )?metrics? (?:for|in) ([^.]+)", "performance", "histogram", "HIGH"),
            (r"no (?:latency )?metrics? (?:for|in) ([^.]+)", "performance", "histogram", "HIGH"),
            (r"should add (?:a )?counter (?:for|to) ([^.]+)", "business", "counter", "MEDIUM"),
        ]

        for pattern, category, metric_type, priority in patterns:
            matches = re.findall(pattern, text.lower())
            for match in matches:
                gaps.append(MetricsGap(
                    description=f"Missing {metric_type} metrics for {match}",
                    category=category,
                    metric_type=metric_type,
                    priority=priority,
                    affected_components=[],
                    suggested_metric_names=[],
                ))

        return gaps[:5]

    def _find_error_analysis(self, text: str, error_type: str) -> Optional[str]:
        """Find analysis for a specific error type in text."""
        error_lower = error_type.lower()

        # Look for sentences mentioning this error
        sentences = text.split(".")
        for sentence in sentences:
            if error_lower in sentence.lower():
                # Check if it contains analysis keywords
                if any(kw in sentence.lower() for kw in ["caused by", "due to", "because", "likely", "root cause"]):
                    return sentence.strip()

        return None
