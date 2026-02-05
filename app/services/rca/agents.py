import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rca.builder import AgentExecutorBuilder
from app.services.rca.capabilities import (
    ExecutionContext,
    IntegrationCapabilityResolver,
)
from app.services.rca.context_utils import (
    build_context_string,
    format_thread_history_for_prompt,
    get_context_summary,
)
from app.services.rca.prompts import CONVERSATIONAL_INTENT_PROMPT, RCA_SYSTEM_PROMPT
from app.services.rca.state import Hypothesis, RCAState

logger = logging.getLogger(__name__)


def _disable_tool_calling(llm: Any, stage: str) -> Any:
    """Return an LLM instance with tool calling disabled (tool_choice=none).

    Tries tool_choice="none" first, falls back to empty tool binding,
    and finally returns the original LLM if neither works.
    """
    bind_tools = getattr(llm, "bind_tools", None)
    if not callable(bind_tools):
        return llm

    try:
        return llm.bind_tools([], tool_choice="none")
    except Exception as e:
        logger.warning(
            f"{stage}: failed to disable tool calling via tool_choice=none; "
            f"falling back to empty tool binding ({type(e).__name__}: {e})"
        )
        try:
            return llm.bind_tools([])
        except Exception as e2:
            logger.warning(
                f"{stage}: failed to bind empty tools; using original llm "
                f"({type(e2).__name__}: {e2})"
            )
            return llm


def _add_trace(state: RCAState, stage: str, details: Dict[str, Any]) -> None:
    """Append a timestamped entry to the RCA execution trace."""
    state["trace"].append({"stage": stage, "details": details})


def _get_service_name(state: RCAState) -> Optional[str]:
    """Extract the failing service name from state or nested context."""
    return state.get("failing_service") or state.get("context", {}).get(
        "failing_service"
    )


def _get_repos(state: RCAState) -> List[str]:
    """Resolve repository names for the failing service using the service→repo mapping."""
    context = state.get("context", {})
    mapping = context.get("service_repo_mapping") or {}
    service_name = _get_service_name(state)
    if service_name and isinstance(mapping, dict):
        repos = mapping.get(service_name)
        if isinstance(repos, list) and repos:
            return [r for r in repos if isinstance(r, str)]
    repo_name = context.get("repo_name")
    if isinstance(repo_name, str) and repo_name:
        return [repo_name]
    return []


def _extract_json(text: str) -> Optional[Any]:
    """Best-effort JSON extraction from LLM output.

    Handles markdown code fences and locates the outermost JSON object or array.
    Returns None if no valid JSON is found.
    """
    cleaned = text.strip()
    if not cleaned:
        return None

    candidates: List[str] = []
    fence_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.I)
    candidates.extend([m.strip() for m in fence_matches if m.strip()])
    candidates.append(cleaned)

    for candidate in candidates:
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = candidate.find(start_char)
            end = candidate.rfind(end_char)
            if start == -1 or end == -1 or end <= start:
                continue
            snippet = candidate[start : end + 1].strip()
            try:
                return json.loads(snippet)
            except Exception:
                continue
    return None


async def classify_query_intent(state: RCAState, llm: BaseChatModel) -> RCAState:
    """
    Classify user query to determine if it's conversational or an RCA investigation.

    Uses thread_history if available to understand context for vague follow-up queries
    like "check again", "what about it?", etc.
    """
    query = state.get("task", "").strip()
    if not query:
        state["query_intent"] = "other"
        return state

    try:
        # Get thread history for context (helps with vague follow-ups like "check again")
        thread_history_text = format_thread_history_for_prompt(
            state, max_length=settings.RCA_THREAD_HISTORY_MAX_LENGTH
        )

        # Format prompt with query and optional thread history
        prompt = CONVERSATIONAL_INTENT_PROMPT.format(
            query=query, thread_history=thread_history_text
        )

        # Disable tool calling for intent classification - this agent should only return text
        # For Groq, we need to use tool_choice="none" instead of bind_tools([])
        llm_no_tools = _disable_tool_calling(llm=llm, stage="intent_classification")
        resp = await llm_no_tools.ainvoke([HumanMessage(content=prompt)])
        intent = getattr(resp, "content", "").strip().lower()

        state["query_intent"] = intent
        if thread_history_text:
            logger.info(
                f"Classified query '{query[:50]}' as: {intent} (with thread history)"
            )
        else:
            logger.info(f"Classified query '{query[:50]}' as: {intent}")
    except Exception as e:
        logger.warning(f"Intent classification failed: {e}, defaulting to RCA")
        state["query_intent"] = "rca_investigation"

    return state


def _build_conversational_prompt() -> ChatPromptTemplate:
    system = (
        "You are a helpful SRE assistant that can answer questions about services, repositories, "
        "code, commits, and environments. Use the available tools to gather information and provide "
        "clear, helpful responses.\n\n"
        "**Available Tools:**\n"
        "- Repository tools: List repos, get commits, view PRs, get repository metadata\n"
        "- Code tools: Read files (automatically parses functions/classes), search code\n"
        "- Environment tools: Get environment info, deployed commits\n\n"
        "**Context:**\n"
        "You have access to the 'Context' provided at the end of this message, which includes "
        "connected services, repositories, environments, and deployed commits. Always check this context first "
        "before calling tools to list services or environments.\n\n"
        "**CRITICAL: When Asking About Deployed Code:**\n"
        "If the user asks about commits/code that's DEPLOYED in an environment (e.g., "
        '"commits on deployed code", "what\'s in test environment", "code in production"), '
        "you MUST use the deployed commit SHA from the environment context.\n\n"
        "**Finding the deployed commit SHA:**\n"
        "1. Check the 'Deployed commits' in the Context to find the deployed commit SHA for that environment\n"
        "2. Extract just the repository name (after the slash) from the full repo name\n"
        "3. Use the full commit SHA (not the shortened 7-char version shown in context)\n\n"
        "**ALL tools support environment-specific commits:**\n"
        "- get_repository_commits_tool(repo_name='...', commit_sha='<deployed_sha>') - shows commits UP TO deployment\n"
        "- read_repository_file_tool(repo_name='...', file_path='...', commit_sha='<deployed_sha>') - reads file from deployment\n"
        "- download_file_tool(repo_name='...', file_path='...', ref='<deployed_sha>') - downloads file from deployment\n"
        "- get_repository_tree_tool(repo_name='...', expression='<deployed_sha>:path/') - explores files from deployment\n\n"
        "**Examples:**\n"
        "Context shows: 'Deployed commits: test: Vibe-Monitor/marketplace@ab2f9b1'\n"
        "- User asks: 'what are the last 5 commits on deployed code?'\n"
        "  → Call: get_repository_commits_tool(repo_name='marketplace', first=5, commit_sha='ab2f9b1c73b71809ba273d68b0ad4312c500190c')\n"
        "- User asks: 'read app.py from test environment'\n"
        "  → Call: read_repository_file_tool(repo_name='marketplace', file_path='app.py', commit_sha='ab2f9b1c73b71809ba273d68b0ad4312c500190c')\n"
        "- User asks: 'show me the code structure in production'\n"
        "  → Call: get_repository_tree_tool(repo_name='marketplace', expression='ab2f9b1c73b71809ba273d68b0ad4312c500190c:')\n\n"
        "**Guidelines:**\n"
        "- Use the context provided to answer questions about what services/repos are connected.\n"
        "- Use tools only when necessary (e.g. for reading code, fetching commits).\n"
        "- Be concise and friendly.\n"
        "- If you can't find information, say so clearly."
    )
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )


def _get_context_info(
    execution_context: ExecutionContext, state: RCAState
) -> Dict[str, Any]:
    """
    Extract context info for responses.

    NOTE: This is a wrapper around get_context_summary for backward compatibility.
    New code should use get_context_summary directly from context_utils.
    """
    return get_context_summary(execution_context, state)


async def conversational_agent(
    state: RCAState,
    llm: BaseChatModel,
    execution_context: ExecutionContext,
    callbacks: Optional[List] = None,
) -> RCAState:
    """
    Handle conversational queries with tool access.
    """
    query = state.get("task", "").strip()

    if not query:
        state["report"] = "I didn't receive a query. How can I help you?"
        return state

    # Get tools for conversational queries (repository info, code read, code search)
    from app.services.rca.capabilities import Capability

    conversational_capabilities = {
        Capability.REPOSITORY_INFO,  # List repos, commits, PRs
        Capability.CODE_READ,  # Read files, parse code
        Capability.CODE_SEARCH,  # Search code
    }

    # Use available capabilities from execution context
    available_capabilities = (
        execution_context.capabilities & conversational_capabilities
    )

    if not available_capabilities:
        # Fallback: try to get basic tools even if no integrations
        available_capabilities = conversational_capabilities

    try:
        builder = (
            AgentExecutorBuilder(llm=llm, prompt=_build_conversational_prompt())
            .with_context(execution_context)
            .with_capabilities(available_capabilities)
        )

        if callbacks:
            builder = builder.with_callbacks(callbacks)

        executor = builder.build()

        # Format input with context using helper function
        context_string = build_context_string(execution_context, state)

        input_text = query
        if context_string:
            input_text = f"{query}\n\nContext: {context_string}"

        result = await executor.ainvoke({"input": input_text})
        output = result.get("output") if isinstance(result, dict) else None

        if output:
            state["report"] = output
            _add_trace(
                state,
                "conversational",
                {"query": query, "response_length": len(output)},
            )
        else:
            state["report"] = "I apologize, but I couldn't generate a response."

    except Exception as e:
        logger.error(f"Error in conversational agent: {e}", exc_info=True)
        state["report"] = (
            "I encountered an error while processing your request. Please try again."
        )

    return state


async def resolve_execution_context_agent(
    state: RCAState, db: Optional[AsyncSession]
) -> RCAState:
    if state.get("execution_context") is not None:
        return state

    workspace_id = state["workspace_id"]
    ctx = state.get("context", {}) or {}
    service_mapping = ctx.get("service_repo_mapping") or {}
    thread_history = ctx.get("thread_history")

    if db is None:
        execution_context = ExecutionContext(
            workspace_id=workspace_id,
            capabilities=set(),
            integrations={},
            service_mapping=service_mapping
            if isinstance(service_mapping, dict)
            else {},
            thread_history=thread_history if isinstance(thread_history, str) else None,
        )
    else:
        resolver = IntegrationCapabilityResolver(only_healthy=True)
        execution_context = await resolver.resolve(
            workspace_id=workspace_id,
            db=db,
            service_mapping=service_mapping
            if isinstance(service_mapping, dict)
            else {},
            thread_history=thread_history if isinstance(thread_history, str) else None,
        )

    state["execution_context"] = execution_context
    _add_trace(
        state,
        "resolve_context",
        {
            "workspace_id": workspace_id,
            "capabilities": sorted([c.value for c in execution_context.capabilities]),
            "integrations": sorted(list(execution_context.integrations.keys())),
        },
    )
    return state


async def hypothesis_agent(state: RCAState, llm: BaseChatModel) -> RCAState:
    iteration = int(state.get("iteration") or 0)
    if state.get("hypotheses"):
        state.setdefault("history", [])
        state["history"].append(
            {
                "iteration": iteration,
                "hypotheses": state["hypotheses"],
            }
        )

    failing_service = _get_service_name(state)
    repos = _get_repos(state)
    evidence_board = state.get("evidence_board") or {}

    # Get service→repo mapping for context
    ctx = state.get("context", {}) or {}
    service_mapping = ctx.get("service_repo_mapping") or {}
    mapping_text = json.dumps(service_mapping) if service_mapping else "{}"

    prompt = (
        "Generate 5-8 distinct RCA hypotheses for this incident.\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{ "hypotheses": [ {"hypothesis": "..."} ] }\n'
        "Do not include markdown.\n\n"
        f"Task: {state.get('task')}\n"
        f"Failing service (for logs): {failing_service}\n"
        f"Repository name (for GitHub): {repos[: settings.RCA_MAX_REPOS_IN_PROMPT]}\n"
        f"SERVICE→REPOSITORY mapping: {mapping_text}\n"
        f"Timeframe: {state.get('timeframe')}\n"
        f"Severity: {state.get('severity')}\n"
        f"Previous evidence summary: {json.dumps(evidence_board)[: settings.RCA_EVIDENCE_SUMMARY_MAX_LENGTH]}\n"
    )

    try:
        # Disable tool calling for hypothesis generation - this agent should only return JSON
        # For Groq, we need to use tool_choice="none" instead of bind_tools([])
        llm_no_tools = _disable_tool_calling(llm=llm, stage="hypothesis_generation")
        resp = await llm_no_tools.ainvoke(
            [SystemMessage(content=RCA_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        content = getattr(resp, "content", None) if resp is not None else None
        payload = _extract_json(str(content or ""))
        hypotheses_raw = (
            payload.get("hypotheses") if isinstance(payload, dict) else None
        )
        hypotheses: List[Hypothesis] = []
        if isinstance(hypotheses_raw, list):
            for item in hypotheses_raw:
                if isinstance(item, dict) and isinstance(item.get("hypothesis"), str):
                    text = item["hypothesis"].strip()
                    if text:
                        hypotheses.append(
                            Hypothesis(
                                hypothesis=text, evidence={}, validation="pending"
                            )
                        )
        if not hypotheses:
            # Fallback if no hypotheses could be parsed: create a generic one
            hypotheses = [
                Hypothesis(
                    hypothesis="Investigate the reported issue to determine root cause.",
                    evidence={},
                    validation="pending",
                )
            ]
        state["hypotheses"] = hypotheses[:10]
        _add_trace(
            state,
            "hypotheses",
            {"count": len(state["hypotheses"]), "iteration": iteration},
        )
        return state
    except Exception as e:
        logger.exception("Hypothesis generation failed")
        # Generic fallback
        state["hypotheses"] = [
            Hypothesis(
                hypothesis="Investigate the reported issue to determine root cause.",
                evidence={},
                validation="pending",
            )
        ]
        _add_trace(
            state,
            "hypotheses",
            {
                "error": str(e),
                "count": len(state["hypotheses"]),
                "iteration": iteration,
            },
        )
        return state


def _build_evidence_prompt() -> ChatPromptTemplate:
    system = (
        RCA_SYSTEM_PROMPT + "\n\n"
        "You are the EvidenceGatherer agent in a closed-loop RCA system.\n"
        "Use the available tools to gather evidence for the hypotheses.\n"
        "Prefer deterministic evidence over assumptions.\n"
        "\n"
        "**CRITICAL TOOL USAGE RULES:**\n"
        "- ONLY call tools from your available tools list\n"
        "- NEVER call non-existent tools like 'json', 'parse', 'format', etc.\n"
        "- Tool responses are already in JSON format - just read them directly\n"
        "- When you finish gathering evidence, return ONLY valid JSON (no markdown)\n"
        "- Do NOT try to call a 'json' tool - there is no such tool\n"
        "\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{ "evidence_board": { "global": { "notes": "..." }, "by_hypothesis": [ { "hypothesis": "...", "evidence": { "signals": [], "code": [], "logs": [], "metrics": [] } } ] } }'
    )
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )


def _format_evidence_input(state: RCAState, execution_context: ExecutionContext) -> str:
    service_name = _get_service_name(state)
    repos = _get_repos(state)
    ctx = state.get("context", {}) or {}

    env = ctx.get("environment_context") or {}
    max_env = settings.RCA_ENV_CONTEXT_MAX_LENGTH
    env_text = (
        json.dumps(env)[:max_env] if isinstance(env, dict) else str(env)[:max_env]
    )

    hypotheses = state.get("hypotheses") or []
    hypotheses_text = json.dumps(hypotheses)[: settings.RCA_HYPOTHESES_MAX_LENGTH]

    # Get the service→repo mapping for explicit instruction
    service_mapping = execution_context.service_mapping or {}
    mapping_text = json.dumps(service_mapping) if service_mapping else "{}"

    return (
        f"Task: {state.get('task')}\n"
        f"Failing service: {service_name}\n"
        f"Repos for this service: {repos[: settings.RCA_MAX_REPOS_IN_PROMPT]}\n"
        f"Timeframe: {state.get('timeframe')}\n"
        f"Severity: {state.get('severity')}\n"
        f"Environment context: {env_text}\n"
        f"Known integrations: {sorted(list(execution_context.integrations.keys()))}\n"
        f"Hypotheses to investigate: {hypotheses_text}\n"
        "\n"
        f"**SERVICE→REPOSITORY MAPPING (CRITICAL - USE THIS!):**\n"
        f"{mapping_text}\n"
        "\n"
        "**⚠️ CRITICAL: SERVICE NAMES vs REPOSITORY NAMES:**\n"
        "- For LOG tools (fetch_logs_tool, fetch_error_logs_tool): Use SERVICE NAME (e.g., 'marketplace-service')\n"
        "- For GITHUB tools (download_file_tool, get_repository_commits_tool, etc.): Use REPOSITORY NAME from the mapping above!\n"
        f"- Example: If investigating '{service_name}', check mapping above to find the repo name\n"
        "- WRONG: download_file_tool(repo_name='service-name') ❌\n"
        "- RIGHT: download_file_tool(repo_name='repo-name') ✅ (if mapping shows service-name→repo-name)\n"
        "\n"
        "**CRITICAL INSTRUCTIONS:**\n"
        "- Call tools to gather evidence for each hypothesis\n"
        "- **IF OBSERVABILITY TOOLS FAIL** (Grafana/Loki unreachable): IMMEDIATELY fall back to code reading:\n"
        "  1. Use `search_code_tool` to find the service repository\n"
        "  2. Use `download_file_tool` to read the main file (app.py, server.js, main.go, etc.)\n"
        "  3. Prefer the `parsed` and `interesting_lines` fields from the tool response over reading full file content\n"
        "  4. Only call `parse_code_tool(code=..., language=...)` if the tool response did not include `parsed`\n"
        "  5. Code often contains the root cause (latency injections, inefficient queries, etc.)\n"
        "- If a tool fails (e.g., 'All connection attempts failed'), note it and try other tools OR read code\n"
        "- After gathering evidence, return ONLY valid JSON with an `evidence_board`\n"
        "- DO NOT try to call a 'json' tool - there is no such tool\n"
        "- Tool responses are already JSON - just read them directly\n"
        "- If a tool requires a label key or metric name, discover it first using get_labels_tool or get_label_values_tool\n"
    )


async def evidence_agent(
    state: RCAState,
    llm: BaseChatModel,
    execution_context: ExecutionContext,
    callbacks: Optional[List[Any]] = None,
) -> RCAState:
    state["iteration"] = int(state.get("iteration") or 0) + 1

    if not execution_context.capabilities:
        state["evidence_board"] = {
            "global": {
                "note": "No healthy integrations available for evidence gathering."
            },
            "by_hypothesis": [],
        }
        _add_trace(
            state,
            "evidence",
            {
                "iteration": state["iteration"],
                "tool_steps": 0,
                "has_evidence_board": True,
            },
        )
        return state

    # Build prompt with explicit tool list to prevent calling non-existent tools
    prompt_template = _build_evidence_prompt()

    # Get available tool names from tool registry
    from app.services.rca.builder import ToolRegistry

    tool_registry = ToolRegistry()
    available_tools = tool_registry.get_tools_for_capabilities(
        execution_context.capabilities
    )
    available_tool_names = (
        [tool.name for tool in available_tools] if available_tools else []
    )

    # Enhance prompt with actual tool names
    if available_tool_names:
        tool_list_text = ", ".join(sorted(available_tool_names))
        enhanced_system = (
            RCA_SYSTEM_PROMPT + "\n\n"
            "You are the EvidenceGatherer agent in a closed-loop RCA system.\n"
            "Use the available tools to gather evidence for the hypotheses.\n"
            "Prefer deterministic evidence over assumptions.\n"
            "\n"
            "**CRITICAL TOOL USAGE RULES:**\n"
            f"- Your available tools are: {tool_list_text}\n"
            "- ONLY call tools from this list - NEVER call tools that are not listed\n"
            "- There is NO 'json' tool, NO 'parse' tool, NO 'format' tool in your available tools\n"
            "- Tool responses are already in JSON format - just read them directly\n"
            "- When you finish gathering evidence, return ONLY valid JSON (no markdown)\n"
            "- Do NOT try to call a 'json' tool - there is no such tool\n"
        )
        prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", enhanced_system),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

    builder = AgentExecutorBuilder(llm=llm, prompt=prompt_template).with_context(
        execution_context
    )
    if callbacks:
        builder = builder.with_callbacks(callbacks)
    executor = builder.build()

    try:
        result = await executor.ainvoke(
            {"input": _format_evidence_input(state, execution_context)}
        )
        output = result.get("output") if isinstance(result, dict) else None
        payload = _extract_json(str(output or ""))
        evidence_board = (
            payload.get("evidence_board") if isinstance(payload, dict) else None
        )
        if (
            evidence_board
            and isinstance(evidence_board, dict)
            and ("global" in evidence_board or "by_hypothesis" in evidence_board)
        ):
            state["evidence_board"] = evidence_board
        else:
            steps = (
                result.get("intermediate_steps") if isinstance(result, dict) else None
            )
            state["evidence_board"] = _build_minimal_evidence_board_from_steps(
                state=state, steps=steps
            )

        by_hyp = None
        if isinstance(evidence_board, dict):
            by_hyp = evidence_board.get("by_hypothesis")
        if isinstance(by_hyp, list):
            hyp_map: Dict[str, Dict[str, Any]] = {}
            for item in by_hyp:
                if not isinstance(item, dict):
                    continue
                h = item.get("hypothesis")
                e = item.get("evidence")
                if isinstance(h, str) and isinstance(e, dict):
                    hyp_map[h.strip()] = e
            for h in state.get("hypotheses") or []:
                key = (h.get("hypothesis") or "").strip()
                if key and key in hyp_map:
                    h["evidence"] = hyp_map[key]

        steps = result.get("intermediate_steps") if isinstance(result, dict) else None
        _add_trace(
            state,
            "evidence",
            {
                "iteration": state["iteration"],
                "tool_steps": len(steps) if isinstance(steps, list) else 0,
                "has_evidence_board": bool(state.get("evidence_board")),
            },
        )
        return state
    except Exception as e:
        logger.exception("Evidence gathering failed")
        state["evidence_board"] = {
            "global": {"note": "Evidence gathering failed due to an internal error."},
            "by_hypothesis": [],
        }
        _add_trace(
            state, "evidence", {"iteration": state["iteration"], "error": str(e)}
        )
        return state


def _build_minimal_evidence_board_from_steps(
    state: RCAState, steps: Optional[Any]
) -> Dict[str, Any]:
    hypotheses = state.get("hypotheses") or []
    by_hypothesis: List[Dict[str, Any]] = []
    for h in hypotheses:
        hypothesis_text = (h.get("hypothesis") or "").strip()
        if not hypothesis_text:
            continue
        by_hypothesis.append(
            {
                "hypothesis": hypothesis_text,
                "evidence": {"signals": [], "code": [], "logs": [], "metrics": []},
            }
        )

    notes: List[str] = []
    if isinstance(steps, list):
        import json as _json

        for item in steps[:20]:
            try:
                action, observation = item
            except Exception:
                continue
            tool = (
                getattr(action, "tool", None)
                or getattr(action, "tool_name", None)
                or "tool"
            )
            obs_text = str(observation or "")
            snippet = obs_text.strip()[:1200]
            if snippet:
                notes.append(f"{tool}: {snippet}")

            parsed_observation: Any = None
            if isinstance(observation, (dict, list)):
                parsed_observation = observation
            else:
                stripped = obs_text.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        parsed_observation = _json.loads(stripped)
                    except Exception:
                        parsed_observation = None

            if not isinstance(parsed_observation, dict):
                continue

            interesting_lines = parsed_observation.get("interesting_lines")
            parsed_block = parsed_observation.get("parsed")

            hits: list[dict] = []
            if isinstance(interesting_lines, list):
                hits.extend([x for x in interesting_lines if isinstance(x, dict)])
            if isinstance(parsed_block, dict):
                findings = parsed_block.get("findings")
                if isinstance(findings, list):
                    hits.extend([x for x in findings if isinstance(x, dict)])

            if not hits:
                continue

            bucket = "signals"
            if isinstance(parsed_observation.get("file_path"), str) or isinstance(
                parsed_observation.get("excerpt"), str
            ):
                bucket = "code"
            elif "log" in str(tool).lower():
                bucket = "logs"
            elif "metric" in str(tool).lower():
                bucket = "metrics"

            for hit in hits[:30]:
                signal = hit.get("type")
                if not isinstance(signal, str) or not signal:
                    continue
                entry = {
                    "source": tool,
                    "signal": signal,
                    "line": hit.get("line"),
                    "text": hit.get("text"),
                }
                for row in by_hypothesis:
                    row["evidence"][bucket].append(dict(entry))

    if not by_hypothesis:
        by_hypothesis = []

    return {
        "global": {
            "notes": "\n\n".join(notes)[: settings.RCA_EVIDENCE_BOARD_MAX_LENGTH]
        },
        "by_hypothesis": by_hypothesis,
    }


def _build_validation_messages(state: RCAState) -> List[Any]:
    evidence_board = state.get("evidence_board") or {}
    hypotheses = state.get("hypotheses") or []
    prompt = (
        "Validate each hypothesis using the evidence.\n"
        "For each hypothesis, choose ONE status: validated | rejected | needs_more_evidence.\n"
        "Provide a confidence integer 0-100, a brief rationale, and 1-3 concrete next steps.\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{ "results": [ {"hypothesis": "...", "status": "validated", "confidence": 0, "rationale": "...", "next_steps": ["..."]} ] }\n'
        "Do not include markdown.\n\n"
        f"Task: {state.get('task')}\n"
        f"Hypotheses: {json.dumps(hypotheses)[: settings.RCA_HYPOTHESES_MAX_LENGTH]}\n"
        f"Evidence board: {json.dumps(evidence_board)[: settings.RCA_VALIDATION_EVIDENCE_MAX_LENGTH]}\n"
    )
    return [SystemMessage(content=RCA_SYSTEM_PROMPT), HumanMessage(content=prompt)]


async def validation_agent(state: RCAState, llm: BaseChatModel) -> RCAState:
    try:
        # Disable tool calling for validation - this agent should only return JSON
        # For Groq, we need to use tool_choice="none" instead of bind_tools([])
        llm_no_tools = _disable_tool_calling(llm=llm, stage="validation")
        resp = await llm_no_tools.ainvoke(_build_validation_messages(state))
        content = getattr(resp, "content", None) if resp is not None else None
        payload = _extract_json(str(content or ""))
        results = payload.get("results") if isinstance(payload, dict) else None
        updated = 0
        if isinstance(results, list):
            by_h: Dict[str, Dict[str, Any]] = {}
            for item in results:
                if not isinstance(item, dict):
                    continue
                h = item.get("hypothesis")
                if not isinstance(h, str):
                    continue
                by_h[h.strip()] = item
            for hyp in state.get("hypotheses") or []:
                key = (hyp.get("hypothesis") or "").strip()
                data = by_h.get(key)
                if not isinstance(data, dict):
                    continue
                status = data.get("status")
                if status in {"validated", "rejected", "needs_more_evidence"}:
                    hyp["validation"] = str(status)
                    conf = data.get("confidence")
                    if isinstance(conf, int):
                        hyp["confidence"] = max(0, min(100, conf))
                    rationale = data.get("rationale")
                    if isinstance(rationale, str) and rationale.strip():
                        hyp["rationale"] = rationale.strip()[:1000]
                    ns = data.get("next_steps")
                    if isinstance(ns, list):
                        cleaned = [str(s).strip() for s in ns if str(s).strip()]
                        hyp["next_steps"] = cleaned[:5]
                    updated += 1

        validated = [
            h
            for h in state.get("hypotheses") or []
            if h.get("validation") == "validated"
        ]
        _add_trace(
            state,
            "validation",
            {
                "updated": updated,
                "validated": len(validated),
                "best_confidence": max(
                    [int(h.get("confidence") or 0) for h in validated], default=0
                ),
            },
        )
        return state
    except Exception as e:
        logger.exception("Validation failed")
        _add_trace(state, "validation", {"error": str(e)})
        return state


def _pick_best_hypothesis(
    state: RCAState,
) -> Tuple[Optional[Hypothesis], List[Hypothesis]]:
    hyps = state.get("hypotheses") or []
    validated = [h for h in hyps if h.get("validation") == "validated"]
    if validated:
        best = max(validated, key=lambda h: int(h.get("confidence") or 0))
        return best, validated
    needs = [h for h in hyps if h.get("validation") == "needs_more_evidence"]
    if needs:
        best = max(needs, key=lambda h: int(h.get("confidence") or 0))
        return best, []
    return None, []


async def synthesis_agent(state: RCAState, llm: BaseChatModel) -> RCAState:
    best, validated = _pick_best_hypothesis(state)
    evidence_board = state.get("evidence_board") or {}
    task = state.get("task")

    prompt = (
        "Write an RCA report for the incident.\n"
        "Use ONLY evidence-backed claims.\n"
        "Format the report clearly with sections for:\n"
        "- What's going on (summary of the issue)\n"
        "- Root cause (technical explanation)\n"
        "- Evidence (key findings)\n"
        "- Next steps (remediation)\n"
        "\n"
        "Return plain markdown, no code fences.\n\n"
        f"Task: {task}\n"
        f"Best hypothesis: {json.dumps(best)[: settings.RCA_SYNTHESIS_HYPOTHESIS_MAX_LENGTH]}\n"
        f"Validated hypotheses: {json.dumps(validated)[: settings.RCA_SYNTHESIS_VALIDATED_MAX_LENGTH]}\n"
        f"Evidence board: {json.dumps(evidence_board)[: settings.RCA_SYNTHESIS_EVIDENCE_MAX_LENGTH]}\n"
    )

    try:
        # Disable tool calling for synthesis - this agent should only generate text
        # For Groq, we need to use tool_choice="none" instead of bind_tools([])
        llm_no_tools = _disable_tool_calling(llm=llm, stage="synthesis")
        resp = await llm_no_tools.ainvoke(
            [SystemMessage(content=RCA_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        content = (getattr(resp, "content", None) or "").strip()
        report = (
            content
            if content
            else "Could not determine the root cause with the available evidence."
        )
        state["root_cause"] = best.get("hypothesis") if isinstance(best, dict) else None
        state["report"] = report
        _add_trace(
            state,
            "synthesis",
            {
                "root_cause": state.get("root_cause"),
                "validated": len(validated),
                "iteration": int(state.get("iteration") or 0),
            },
        )
        return state
    except Exception as e:
        logger.exception("Synthesis failed")
        state["root_cause"] = best.get("hypothesis") if isinstance(best, dict) else None
        state["report"] = (
            "Could not determine the root cause with the available evidence."
        )
        _add_trace(
            state, "synthesis", {"error": str(e), "root_cause": state.get("root_cause")}
        )
        return state
