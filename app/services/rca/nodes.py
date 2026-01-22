"""
Node implementations for LangGraph RCA Agent V2.
Each node represents a step in the investigation flow.

REDESIGNED ARCHITECTURE:
- Router node: Classifies query as "casual" or "incident"
- Conversational node: Handles casual queries (greetings, info requests, commit queries)
- Structured nodes: Handle incidents with systematic investigation flow (parse → plan → investigate → analyze → generate)
"""

import logging
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Callable
from difflib import SequenceMatcher
from functools import wraps
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from .state import RCAStateV2
from .optimizations import (
    summarize_logs,
    summarize_metrics,
    extract_key_info_from_code,
    summarize_commits,
    extract_field,
    format_dict_for_context,
)
# Removed complex code_analyzer - keeping it simple for v1
from .prompts import (
    ROUTER_PROMPT_V1,
    PARSE_QUERY_PROMPT_V1,
    GENERATE_CASUAL_PROMPT_V1,
    GENERATE_INCIDENT_PROMPT_V1,
    DECIDE_NEXT_STEP_PROMPT_V1,
    EXTRACT_DEPENDENCIES_PROMPT_V1,
    MULTI_LEVEL_RCA_REPORT_PROMPT_V1,
    CONVERSATIONAL_INTENT_PROMPT_V1,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions for Multimodal Support
# ============================================================================

def prepare_multimodal_messages(
    prompt: str,
    files: Optional[List[Dict[str, Any]]] = None
) -> List[HumanMessage]:
    """
    Prepare messages for LLM call, including multimodal content (images/videos) if present.

    LangChain's HumanMessage accepts content as Union[str, list[Union[str, dict]]].
    For multimodal, we pass a list with text and image/video dicts.

    Args:
        prompt: Text prompt
        files: Optional list of file objects with keys: 'content', 'mimetype', 'name'

    Returns:
        List of HumanMessage objects with multimodal content
    """
    # If no files, return simple string content (compatible with all LLM providers)
    if not files:
        return [HumanMessage(content=prompt)]

    # Build content list for multimodal: start with text as proper object
    content_blocks = [{"type": "text", "text": prompt}]

    # Add multimodal content
    for file_obj in files:
        mimetype = file_obj.get("mimetype", "")
        content = file_obj.get("content")  # Base64 encoded or URL

        if mimetype.startswith("image/"):
            # For images, LangChain expects dict with type and image_url
            if isinstance(content, str):
                if content.startswith("data:"):
                    # Data URI format: data:image/png;base64,<base64>
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": content}  # Data URI as URL
                    })
                elif content.startswith("http"):
                    # URL - LangChain can handle this
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": content}
                    })
                else:
                    # Assume base64 string - convert to data URI
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mimetype};base64,{content}"}
                    })
            logger.info(f"Added image to multimodal message: {file_obj.get('name', 'unknown')}")
        elif mimetype.startswith("video/"):
            # For videos, similar handling
            if isinstance(content, str):
                if content.startswith("http"):
                    content_blocks.append({
                        "type": "video_url",
                        "video_url": {"url": content}
                    })
                else:
                    # Base64 video - convert to data URI
                    content_blocks.append({
                        "type": "video_url",
                        "video_url": {"url": f"data:{mimetype};base64,{content}"}
                    })
            logger.info(f"Added video to multimodal message: {file_obj.get('name', 'unknown')}")

    # Return single HumanMessage with all content blocks
    return [HumanMessage(content=content_blocks)]


# ============================================================================
# Helper Functions for Tool Robustness
# ============================================================================

def async_retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Retry decorator for async functions with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each attempt
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except asyncio.TimeoutError:
                    # Don't retry on timeout
                    raise
                except Exception as e:
                    last_exception = e
                    error_str = str(e).lower()
                    
                    # Don't retry on certain errors
                    if any(code in error_str for code in ["404", "not found", "401", "403"]):
                        raise
                    
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {current_delay}s...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"All {max_attempts} attempts failed: {e}")
            
            raise last_exception
        return wrapper
    return decorator


def get_environment_context(state: RCAStateV2) -> Dict[str, Any]:
    """
    Extract environment context from state.
    
    Returns:
        Dictionary with:
            - environments: List of {name, is_default} dicts
            - default_environment: Name of default environment
            - deployed_commits_by_environment: Dict of env_name -> {repo_full_name -> {commit_sha, deployed_at}}
    """
    context = state.get("context", {})
    environment_context = context.get("environment_context", {})
    
    if not environment_context:
        return {
            "environments": [],
            "default_environment": None,
            "deployed_commits_by_environment": {},
        }
    
    return environment_context


def determine_target_environment(
    user_query: str,
    environment_context: Dict[str, Any]
) -> Optional[str]:
    """
    Determine which environment the user is asking about.
    
    Args:
        user_query: User's query (may contain environment name)
        environment_context: Environment context from state
        
    Returns:
        Environment name to use, or None if no environments configured
    """
    environments = environment_context.get("environments", [])
    default_env = environment_context.get("default_environment")
    
    if not environments:
        return None
    
    # Check if user specified an environment in the query using word boundaries
    query_lower = user_query.lower()
    for env in environments:
        env_name = env.get("name", "").lower()
        if env_name:
            # Use word boundary matching to avoid false positives
            # e.g., "production" won't match "production-api" but will match "in production"
            import re as re_module
            pattern = r'\b' + re_module.escape(env_name) + r'\b'
            if re_module.search(pattern, query_lower):
                logger.info(f"User specified environment: {env.get('name')}")
                return env.get("name")
    
    # Default to default environment if available
    if default_env:
        logger.info(f"Using default environment: {default_env}")
        return default_env
    
    # Fallback to first environment
    if environments:
        first_env = environments[0].get("name")
        logger.info(f"Using first available environment: {first_env}")
        return first_env
    
    return None


def get_deployed_commit_sha(
    repo_full_name: str,
    environment_name: str,
    environment_context: Dict[str, Any]
) -> Optional[str]:
    """
    Get the deployed commit SHA for a repository in a specific environment.
    
    Args:
        repo_full_name: Full repository name (e.g., "owner/repo-name")
        environment_name: Environment name
        environment_context: Environment context from state
        
    Returns:
        Commit SHA if found, None otherwise
    """
    deployed_commits = environment_context.get("deployed_commits_by_environment", {})
    env_commits = deployed_commits.get(environment_name, {})
    
    if not env_commits:
        return None
    
    # Try exact match first
    commit_info = env_commits.get(repo_full_name)
    if commit_info:
        if isinstance(commit_info, dict):
            return commit_info.get("commit_sha")
        else:
            # Legacy format where commit_info is just the sha string
            return commit_info
    
    # Try partial match (repo name without owner)
    repo_name_only = repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name
    for repo, commit_info in env_commits.items():
        if repo.endswith(f"/{repo_name_only}") or repo == repo_name_only:
            if isinstance(commit_info, dict):
                return commit_info.get("commit_sha")
            else:
                return commit_info
    
    return None


async def resolve_default_branch_and_fetch_commits(
    commits_tool: Any,
    workspace_id: str,
    repo_name: str,
    first: int = 5
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Resolve the default branch for a repo and fetch commits.

    Tries branches in smart order:
    1. main (most common default)
    2. master (legacy default)
    3. develop (common in gitflow)

    Returns:
        Tuple of (commits_result, successful_branch, attempted_branches)
    """
    # Try common branch names (HEAD doesn't work with GitHub GraphQL API)
    branch_attempts = ["main", "master", "develop"]
    attempted = []
    
    for branch_ref in branch_attempts:
        try:
            # Format ref for GitHub API
            ref = f"refs/heads/{branch_ref}"

            logger.info(f"   Trying {branch_ref}...")
            attempted.append(branch_ref)
            
            result = await commits_tool.ainvoke({
                "workspace_id": workspace_id,
                "repo_name": repo_name,
                "ref": ref,
                "first": first,
            })
            
            # Check if successful
            if result and "Resource not found" not in str(result) and "Error" not in str(result):
                logger.info(f"✅ Successfully resolved default branch: {branch_ref}")
                return (result, branch_ref, attempted)
                
        except Exception as e:
            logger.debug(f"   {branch_ref} failed: {e}")
            continue
    
    logger.warning(f"⚠️ Could not resolve default branch (tried: {', '.join(attempted)})")
    return (None, None, attempted)


async def discover_best_matching_repo(
    list_repos_tool: Any,
    workspace_id: str,
    service_name: str,
    service_mapping: Dict[str, str]
) -> Tuple[Optional[str], float, str]:
    """
    Auto-discover the best matching repository for a service.
    
    Uses name similarity matching when service_mapping doesn't have the service.
    
    Returns:
        Tuple of (repo_name, confidence_score, discovery_method)
    """
    # First check if already in mapping
    if service_name in service_mapping:
        return (service_mapping[service_name], 1.0, "mapping")
    
    # Try exact match with service name as repo name
    if service_mapping and service_name in service_mapping.values():
        logger.info(f"   Found exact repo name match: {service_name}")
        return (service_name, 0.95, "exact_name")
    
    # List all available repos
    try:
        logger.info(f"   Discovering repos to find match for '{service_name}'...")
        repos_result = await list_repos_tool.ainvoke({"workspace_id": workspace_id})
        
        if repos_result and "Error" not in str(repos_result):
            # Extract repo names from the result string
            # Format is typically: "• owner/repo-name"
            repo_names = re.findall(r'[•\-]\s*[\w\-]+/([\w\-]+)', str(repos_result))
            
            if not repo_names:
                # Try alternate format
                repo_names = re.findall(r'`([\w\-]+)`', str(repos_result))
            
            if repo_names:
                # Find best match using fuzzy string matching
                best_match = None
                best_score = 0.0
                
                for repo in repo_names:
                    # Calculate similarity ratio
                    score = SequenceMatcher(None, service_name.lower(), repo.lower()).ratio()
                    
                    # Bonus for exact match (case-insensitive)
                    if service_name.lower() == repo.lower():
                        score = 1.0
                    # Bonus for substring matches
                    elif service_name.lower() in repo.lower() or repo.lower() in service_name.lower():
                        score += 0.2
                    
                    if score > best_score:
                        best_score = score
                        best_match = repo
                
                if best_match and best_score >= 0.75:  # Increased threshold from 0.5 to 0.75
                    logger.info(f"   Found similar repo: {best_match} (confidence: {best_score:.2f})")
                    return (best_match, best_score, "fuzzy_match")
    
    except Exception as e:
        logger.warning(f"   Repo discovery failed: {e}")
    
    # Fallback: assume service name is repo name
    logger.info(f"   Fallback: assuming service '{service_name}' has repo '{service_name}'")
    return (service_name, 0.3, "assumption")


def rank_code_files_by_relevance(
    files: List[str],
    service_name: str,
    preferred_dirs: List[str] = ["src/", "service/", "api/", "app/", "lib/"]
) -> List[str]:
    """
    Rank discovered code files by relevance for investigation.
    
    Prioritizes:
    1. Files matching service name (e.g., payment.py for "payment" service)
    2. Files in preferred directories (src/, service/, api/)
    3. Common entry points (main.*, app.*, server.*, index.*)
    4. Language-specific entry files
    
    Returns:
        Sorted list of file paths (most relevant first)
    """
    scored_files = []
    
    for filepath in files:
        score = 0.0
        filename = filepath.split('/')[-1].lower()
        file_lower = filepath.lower()
        
        # High priority: matches service name
        if service_name.lower() in filename:
            score += 100
        
        # Preferred directories
        for pref_dir in preferred_dirs:
            if file_lower.startswith(pref_dir):
                score += 50
                break
        
        # Common entry point patterns
        entry_patterns = [
            (r'^main\.(py|js|go|java|ts|rb)$', 40),
            (r'^app\.(py|js|ts)$', 40),
            (r'^server\.(py|js|ts|go)$', 40),
            (r'^index\.(js|ts|html)$', 35),
            (r'^__init__\.py$', 30),
            (r'^handler\.(py|js|go)$', 30),
            (r'^service\.(py|js|go)$', 35),
        ]
        
        for pattern, points in entry_patterns:
            if re.match(pattern, filename):
                score += points
                break
        
        # Avoid test/config files
        if any(exclude in file_lower for exclude in ['test', 'spec', 'config', '.yml', '.yaml', '.json', '.md', '.txt']):
            score -= 20
        
        scored_files.append((filepath, score))
    
    # Sort by score descending
    scored_files.sort(key=lambda x: x[1], reverse=True)
    
    return [filepath for filepath, score in scored_files]


def parse_tool_error(error_str: str, tool_name: str, context: str = "") -> Dict[str, Any]:
    """
    Parse and categorize tool errors for better reporting.
    
    Returns:
        Dict with error_type, user_message, and technical_details
    """
    error_lower = str(error_str).lower()
    
    if "404" in error_str or "not found" in error_lower:
        return {
            "error_type": "not_found",
            "user_message": f"{context or 'Resource'} not found or inaccessible",
            "technical_details": f"404: {error_str[:200]}",
            "actionable": f"Verify the {context or 'resource'} name and permissions"
        }
    
    elif "401" in error_str or "403" in error_str or "unauthorized" in error_lower:
        return {
            "error_type": "permission_denied",
            "user_message": f"Permission denied accessing {context or 'resource'}",
            "technical_details": f"Auth error: {error_str[:200]}",
            "actionable": "Check GitHub integration permissions and repository access"
        }
    
    elif "429" in error_str or "rate limit" in error_lower:
        return {
            "error_type": "rate_limit",
            "user_message": "GitHub API rate limit reached",
            "technical_details": f"Rate limit: {error_str[:200]}",
            "actionable": "Wait a moment before retrying, or check rate limit quotas"
        }
    
    elif "timeout" in error_lower:
        return {
            "error_type": "timeout",
            "user_message": f"Request timeout for {context or 'resource'}",
            "technical_details": f"Timeout: {error_str[:200]}",
            "actionable": "Repository might be large; try a more specific query"
        }
    
    else:
        return {
            "error_type": "unknown",
            "user_message": f"Error accessing {context or 'resource'}",
            "technical_details": str(error_str)[:200],
            "actionable": "Check logs for details"
        }


# ============================================================================
# NEW: Helpers for Iterative Multi-Level Investigation
# ============================================================================

async def extract_upstream_dependencies(
    findings: Dict[str, Any],
    llm: BaseChatModel,
    files: Optional[List[Dict[str, Any]]] = None
) -> List[str]:
    """
    Extract upstream service names from investigation findings using LLM.
    
    Args:
        findings: Dict with logs_summary, metrics_summary, code_findings
        llm: Language model for extraction
    
    Returns:
        List of upstream service names
    """
    from .prompts import EXTRACT_DEPENDENCIES_PROMPT_V1
    
    logs_summary = findings.get("logs_summary", "No logs available")
    metrics_summary = findings.get("metrics_summary", "No metrics available")
    code_findings = findings.get("code_findings", "No code findings available")
    
    prompt = EXTRACT_DEPENDENCIES_PROMPT_V1.format(
        logs_summary=str(logs_summary)[:1000],  # Limit length
        metrics_summary=str(metrics_summary)[:1000],
        code_findings=str(code_findings)[:1500]
    )
    
    try:
        messages = prepare_multimodal_messages(prompt, files)
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=30.0
        )
        content = response.content.strip()
        
        if content.upper() == "NONE":
            return []
        
        # Parse line-separated service names
        services = [line.strip() for line in content.split('\n') if line.strip() and line.strip().upper() != "NONE"]
        logger.info(f"Extracted {len(services)} upstream dependencies: {services}")
        return services
        
    except Exception as e:
        logger.error(f"Error extracting dependencies: {e}")
        return []


async def llm_decide_next_step(
    services_investigated: List[Dict[str, Any]],
    current_service: str,
    current_findings: Dict[str, Any],
    llm: BaseChatModel,
    files: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Use LLM to decide if we found root cause or need to investigate upstream.
    
    Args:
        services_investigated: List of {service, findings, depth} dicts
        current_service: Name of service just investigated
        current_findings: Findings for current service
        llm: Language model for decision
    
    Returns:
        Dict with:
            - decision: "ROOT_CAUSE_FOUND" | "INVESTIGATE_UPSTREAM" | "INCONCLUSIVE"
            - reasoning: Explanation
            - upstream_services: List of services to investigate next
            - confidence: 0-100
    """
    from .prompts import DECIDE_NEXT_STEP_PROMPT_V1
    
    # Build investigation history summary
    investigated_summary = ""
    for item in services_investigated:
        svc = item["service"]
        depth = item["depth"]
        findings = item["findings"]
        investigated_summary += f"\n**Level {depth}: `{svc}`**\n"
        if findings.get("logs_summary"):
            investigated_summary += f"  Logs: {str(findings['logs_summary'])[:200]}...\n"
        if findings.get("metrics_summary"):
            investigated_summary += f"  Metrics: {str(findings['metrics_summary'])[:150]}...\n"
        if findings.get("code_findings"):
            investigated_summary += f"  Code: {str(findings['code_findings'])[:200]}...\n"
        if findings.get("commit_findings"):
            investigated_summary += f"  Commits: {str(findings['commit_findings'])[:200]}...\n"
    
    prompt = DECIDE_NEXT_STEP_PROMPT_V1.format(
        services_investigated=investigated_summary,
        current_service=current_service,
        logs_summary=str(current_findings.get("logs_summary", "No logs"))[:1000],
        metrics_summary=str(current_findings.get("metrics_summary", "No metrics"))[:800],
        code_findings=str(current_findings.get("code_findings", "No code"))[:1200],
        commit_findings=str(current_findings.get("commit_findings", "No commits"))[:1000]
    )
    
    try:
        messages = prepare_multimodal_messages(prompt, files)
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=45.0
        )
        content = response.content.strip()
        
        # Parse response
        decision = extract_field(content, "DECISION")
        reasoning = extract_field(content, "REASONING")
        upstream_services_str = extract_field(content, "UPSTREAM_SERVICES")
        confidence = extract_field(content, "CONFIDENCE")
        
        # Parse upstream services
        upstream_services = []
        if upstream_services_str and upstream_services_str.upper() != "NONE":
            upstream_services = [s.strip() for s in upstream_services_str.split(',') if s.strip()]
        
        # Parse confidence
        try:
            confidence_int = int(confidence) if confidence else 50
        except ValueError:
            confidence_int = 50
        
        logger.info(f"LLM Decision: {decision} (confidence: {confidence_int}%)")
        logger.info(f"Reasoning: {reasoning}")
        if upstream_services:
            logger.info(f"Upstream services to investigate: {upstream_services}")
        
        return {
            "decision": decision.upper(),
            "reasoning": reasoning,
            "upstream_services": upstream_services,
            "confidence": confidence_int
        }
        
    except Exception as e:
        logger.error(f"Error in LLM decision: {e}")
        return {
            "decision": "INCONCLUSIVE",
            "reasoning": f"Error making decision: {str(e)}",
            "upstream_services": [],
            "confidence": 0
        }


async def investigate_single_service(
    service: str,
    tools_dict: Dict[str, Any],
    llm: BaseChatModel,
    workspace_id: str,
    user_query: str,
    service_mapping: Dict[str, str],
    environment_context: Dict[str, Any],
    target_environment: Optional[str],
    tools_to_use: List[str]
) -> Dict[str, Any]:
    """
    Investigate a single service (logs, metrics, code, commits).
    
    This is extracted from the original investigate_node to support iterative investigation.
    
    Returns:
        Dict with:
            - logs_summary: Dict[service, summary]
            - metrics_summary: Dict[service, summary]
            - code_findings: Dict[service, findings]
            - commit_findings: Dict[service, findings]
    """
    logger.info(f"🔍 Investigating service: {service}")
    
    findings = {
        "logs_summary": {},
        "metrics_summary": {},
        "code_findings": {},
        "commit_findings": {}
    }
    
    # 1. Check logs - try all available integrations
    if "logs" in tools_to_use:
        logs_fetched = False
        try:
            # Try Grafana logs first (most common)
            if "fetch_logs_tool" in tools_dict:
                logger.info(f"📋 Checking logs for {service} (Grafana)")
                logs_tool = tools_dict["fetch_logs_tool"]
                service_label_key = "service_name"  # Default
                logs_result = await asyncio.wait_for(
                    logs_tool.ainvoke({
                        "service_name": service,
                        "workspace_id": workspace_id,
                        "service_label_key": service_label_key,
                        "search_term": "error OR fail OR exception OR timeout OR refused",
                        "start": "now-2h",
                        "end": "now",
                        "limit": 100,
                    }),
                    timeout=30.0
                )
                if logs_result and isinstance(logs_result, str) and len(logs_result) > 50:
                    if len(logs_result) > 500:
                        summary = await summarize_logs(logs_result, llm)
                        findings["logs_summary"][service] = summary
                        logger.info(f"✅ Logs summary for {service}: {summary[:100]}...")
                    else:
                        findings["logs_summary"][service] = logs_result
                    logs_fetched = True
            
            # Fallback to New Relic
            elif "search_newrelic_logs_tool" in tools_dict:
                logger.info(f"📋 Checking logs for {service} (New Relic)")
                logs_tool = tools_dict["search_newrelic_logs_tool"]
                logs_result = await asyncio.wait_for(
                    logs_tool.ainvoke({
                        "workspace_id": workspace_id,
                        "search_query": f"appName:{service} error OR fail OR exception",
                        "start_hours_ago": 2,
                        "limit": 100,
                    }),
                    timeout=30.0
                )
                if logs_result and len(str(logs_result)) > 100:
                    summary = await summarize_logs(str(logs_result), llm)
                    findings["logs_summary"][service] = summary
                    logger.info(f"✅ Logs for {service} (New Relic)")
                    logs_fetched = True
            
            # Fallback to Datadog
            elif "search_datadog_logs_tool" in tools_dict:
                logger.info(f"📋 Checking logs for {service} (Datadog)")
                logs_tool = tools_dict["search_datadog_logs_tool"]
                logs_result = await asyncio.wait_for(
                    logs_tool.ainvoke({
                        "workspace_id": workspace_id,
                        "service": service,
                        "query": f"service:{service} (error OR fail OR exception)",
                        "start_time": "2h",
                        "limit": 100,
                    }),
                    timeout=30.0
                )
                if logs_result and len(str(logs_result)) > 100:
                    summary = await summarize_logs(str(logs_result), llm)
                    findings["logs_summary"][service] = summary
                    logger.info(f"✅ Logs for {service} (Datadog)")
                    logs_fetched = True
            
            # Fallback to CloudWatch
            elif "search_cloudwatch_logs_tool" in tools_dict:
                logger.info(f"📋 Checking logs for {service} (CloudWatch)")
                logs_tool = tools_dict["search_cloudwatch_logs_tool"]
                logs_result = await asyncio.wait_for(
                    logs_tool.ainvoke({
                        "workspace_id": workspace_id,
                        "log_group_name": f"/aws/service/{service}",
                        "filter_pattern": "error OR fail OR exception",
                        "start_time": "2h",
                        "limit": 100,
                    }),
                    timeout=30.0
                )
                if logs_result and len(str(logs_result)) > 100:
                    summary = await summarize_logs(str(logs_result), llm)
                    findings["logs_summary"][service] = summary
                    logger.info(f"✅ Logs for {service} (CloudWatch)")
                    logs_fetched = True
            
            if not logs_fetched:
                logger.warning(f"⚠️ No logs tool available or no data returned for {service}")
                findings["logs_summary"][service] = "No logs data available"
                        
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Logs fetch timed out for {service} (30s)")
            findings["logs_summary"][service] = "Logs fetch timed out"
        except Exception as e:
            logger.error(f"Error fetching logs for {service}: {e}")
            findings["logs_summary"][service] = f"Error: {str(e)}"
    
    # 2. Check metrics - try all available integrations  
    if "metrics" in tools_to_use:
        metrics_fetched = False
        try:
            # Try Grafana metrics first
            if "fetch_http_latency_tool" in tools_dict or "fetch_cpu_metrics_tool" in tools_dict:
                logger.info(f"📊 Checking metrics for {service} (Grafana)")
                metrics_results = []
                
                if "fetch_http_latency_tool" in tools_dict:
                    latency_tool = tools_dict["fetch_http_latency_tool"]
                    latency_result = await asyncio.wait_for(
                        latency_tool.ainvoke({
                            "workspace_id": workspace_id,
                            "service_name": service,
                            "start_time": "now-2h",
                            "end_time": "now",
                            "step": "60s",
                        }),
                        timeout=30.0
                    )
                    if latency_result:
                        metrics_results.append(f"HTTP Latency: {latency_result}")
                
                if "fetch_cpu_metrics_tool" in tools_dict:
                    cpu_tool = tools_dict["fetch_cpu_metrics_tool"]
                    cpu_result = await asyncio.wait_for(
                        cpu_tool.ainvoke({
                            "workspace_id": workspace_id,
                            "service_name": service,
                            "start_time": "now-2h",
                            "end_time": "now",
                            "step": "60s",
                        }),
                        timeout=30.0
                    )
                    if cpu_result:
                        metrics_results.append(f"CPU: {cpu_result}")
                
                if metrics_results:
                    combined_metrics = "\n".join(metrics_results)
                    findings["metrics_summary"][service] = summarize_metrics({"raw": combined_metrics})
                    logger.info(f"✅ Metrics for {service} (Grafana)")
                    metrics_fetched = True
            
            # Fallback to New Relic
            elif "query_newrelic_metrics_tool" in tools_dict:
                logger.info(f"📊 Checking metrics for {service} (New Relic)")
                metrics_tool = tools_dict["query_newrelic_metrics_tool"]
                metrics_result = await asyncio.wait_for(
                    metrics_tool.ainvoke({
                        "workspace_id": workspace_id,
                        "nrql_query": f"SELECT average(duration), count(*) FROM Transaction WHERE appName = '{service}' SINCE 2 hours ago",
                    }),
                    timeout=30.0
                )
                findings["metrics_summary"][service] = summarize_metrics({"raw": metrics_result})
                logger.info(f"✅ Metrics for {service} (New Relic)")
                metrics_fetched = True
            
            if not metrics_fetched:
                logger.warning(f"⚠️ No metrics tool available or no data returned for {service}")
                findings["metrics_summary"][service] = "No metrics data available"
                    
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Metrics fetch timed out for {service} (30s)")
            findings["metrics_summary"][service] = "Metrics fetch timed out"
        except Exception as e:
            logger.error(f"Error fetching metrics for {service}: {e}")
            findings["metrics_summary"][service] = f"Error: {str(e)}"
    
    # 3. Check code
    if "code" in tools_to_use:
        try:
            repo_name = service_mapping.get(service, service)
            logger.info(f"📖 Reading code from repository: {repo_name}")
            
            # Get deployed commit SHA if available
            deployed_commit_sha = None
            if target_environment:
                deployed_commit_sha = get_deployed_commit_sha(
                    repo_name,
                    target_environment,
                    environment_context
                )
            
            # Try to read code files
            has_download_tool = "download_file_tool" in tools_dict
            has_tree_tool = "get_repository_tree_tool" in tools_dict
            
            if has_tree_tool and has_download_tool:
                tree_tool = tools_dict["get_repository_tree_tool"]
                code_tool = tools_dict["download_file_tool"]
                
                logger.info(f"   Discovering files in {repo_name} repository...")
                
                # Resolve default branch first (don't assume HEAD/main/master!)
                default_branch = None
                if "get_branch_recent_commits_tool" in tools_dict:
                    commits_tool = tools_dict["get_branch_recent_commits_tool"]
                    _, default_branch, _ = await resolve_default_branch_and_fetch_commits(
                        commits_tool, workspace_id, repo_name, first=1
                    )
                
                # Use deployed commit SHA if available, otherwise use resolved default branch
                if deployed_commit_sha:
                    tree_expression = f"{deployed_commit_sha}:"
                    logger.debug(f"   Using deployed commit SHA: {deployed_commit_sha[:8]}...")
                elif default_branch:
                    tree_expression = f"{default_branch}:"
                    logger.debug(f"   Using resolved default branch: {default_branch}")
                else:
                    tree_expression = "HEAD:"
                    logger.warning(f"   Could not resolve default branch, trying HEAD (may fail)")
                
                tree_result = await tree_tool.ainvoke({
                    "workspace_id": workspace_id,
                    "repo_name": repo_name,
                    "expression": tree_expression,
                })
                
                # Extract ALL filenames from tree (don't assume extensions!)
                code_found = False
                code_summaries = []
                files_successfully_read = []
                
                if tree_result and "Error" not in str(tree_result):
                    tree_str = str(tree_result)
                    
                    # Extract ALL files from tree (match any file path, not just code extensions)
                    all_files_raw = re.findall(r'📄\s+([^\s(]+)', tree_str)
                    
                    # Filter to code files (but be flexible - include common config files too)
                    code_extensions = {'.py', '.js', '.go', '.java', '.ts', '.rb', '.cpp', '.c', '.rs', '.php', '.swift', '.kt'}
                    config_patterns = ['docker-compose', 'Dockerfile', 'package', 'requirements', 'go.mod', 'pom.xml', 'yaml', 'yml', 'json', 'toml', 'ini', 'conf']
                    
                    all_files = []
                    for f in all_files_raw:
                        has_code_ext = any(f.endswith(ext) for ext in code_extensions)
                        has_config_pattern = any(pattern in f.lower() for pattern in config_patterns)
                        if has_code_ext or has_config_pattern:
                            all_files.append(f)

                    # Use smart ranking helper
                    files_to_try = rank_code_files_by_relevance(all_files, service)

                    # Simple approach: Read ALL files in ranked order (no hardcoding)
                    files_to_read = files_to_try  # Use ranking from rank_code_files_by_relevance
                    
                    logger.info(f"   📖 Reading {len(files_to_read)} files (main files first)")
                    
                    for file_path in files_to_read:
                        try:
                            logger.info(f"   Reading: {file_path}")
                            tool_params = {
                                "workspace_id": workspace_id,
                                "repo_name": repo_name,
                                "file_path": file_path,
                            }
                            if deployed_commit_sha:
                                tool_params["ref"] = deployed_commit_sha
                            
                            code_result = await asyncio.wait_for(
                                code_tool.ainvoke(tool_params),
                                timeout=30,
                            )
                            
                            if code_result and "Error" not in str(code_result) and "not found" not in str(code_result).lower():
                                # Analyze the full file (no truncation)
                                summary = await extract_key_info_from_code(str(code_result), llm)
                                code_summaries.append(f"{file_path}: {summary}")
                                files_successfully_read.append(file_path)
                                logger.info(f"✅ Analyzed {file_path}")
                                code_found = True
                        except Exception as e:
                            logger.warning(f"   Error reading {file_path}: {str(e)[:100]}")
                            continue
                    
                    if code_found and code_summaries:
                        findings["code_findings"][service] = "\n".join(code_summaries)
                        logger.info(f"✅ Read {len(files_successfully_read)} files for {service}")
                elif not code_found:
                    findings["code_findings"][service] = "Could not access code files"
            else:
                findings["code_findings"][service] = "Code tools not available"
                    
        except Exception as e:
            logger.error(f"Error reading code for {service}: {e}")
            findings["code_findings"][service] = f"Error: {str(e)}"
    
    # 4. Check commits
    if "commits" in tools_to_use:
        try:
            repo_name = service_mapping.get(service, service)
            
            if "get_branch_recent_commits_tool" in tools_dict:
                commits_tool = tools_dict["get_branch_recent_commits_tool"]
                logger.info(f"📜 Checking recent commits in {repo_name}")
                
                commits_result, successful_branch, _ = await resolve_default_branch_and_fetch_commits(
                    commits_tool, workspace_id, repo_name, first=5
                )
                
                if commits_result:
                    findings["commit_findings"][service] = summarize_commits(commits_result)
                    logger.info(f"✅ Commits for {service} from {successful_branch}")
                else:
                    findings["commit_findings"][service] = "Could not fetch commits"
            else:
                findings["commit_findings"][service] = "Commit tool not available"
                    
        except Exception as e:
            logger.error(f"Error fetching commits for {service}: {e}")
            findings["commit_findings"][service] = f"Error: {str(e)}"
    
    return findings


# ============================================================================
# Node 0: ROUTER (NEW - Classifies query type)
# ============================================================================

async def router_node(state: RCAStateV2, llm: BaseChatModel) -> Dict[str, Any]:
    """
    Classify user query as "casual" (greeting, question, info request) or "incident" (problem report).
    
    This is the FIRST node - it determines which path the query takes:
    - Casual queries → conversational_node (flexible ReAct with tools)
    - Incident queries → parse_query_node (structured investigation)
    
    Input: user_query
    Output: query_type ("casual" or "incident")
    """
    logger.info("NODE: router_node")
    
    try:
        query = state["user_query"]
        
        prompt = ROUTER_PROMPT_V1.format(query=query)
        files = state.get("files", [])
        
        # Prepare messages with multimodal support
        messages = prepare_multimodal_messages(prompt, files)
        
        # Add timeout to LLM call
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=30.0
        )
        content = response.content.strip().lower()
        
        # Parse response (should be EXACTLY "casual" or "incident")
        if content == "casual":
            query_type = "casual"
        elif content == "incident":
            query_type = "incident"
        else:
            logger.warning(f"Invalid router response: '{content}'. Falling back to keyword heuristic.")
            incident_keywords = [
                "error",
                "fail",
                "down",
                "slow",
                "broken",
                "issue",
                "problem",
                "outage",
                "crash",
                "timeout",
                "latency",
                "bug",
            ]
            query_lower = query.lower()
            query_type = "incident" if any(k in query_lower for k in incident_keywords) else "casual"
        
        logger.info(f"Query classified as: {query_type}")
        
        # Add to intermediate steps
        intermediate_steps = state.get("intermediate_steps", [])
        intermediate_steps.append({
            "step": "router",
            "result": {
                "query_type": query_type,
                "query": query[:100]
            }
        })
        
        return {
            "query_type": query_type,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in router_node: {e}")
        # On error, default to incident (safer)
        return {
            "query_type": "incident",
            "error": str(e),
        }


# ============================================================================
# Node 0.5: CONVERSATIONAL (NEW - Handles casual queries with ReAct)
# ============================================================================

async def conversational_node(state: RCAStateV2, llm: BaseChatModel, tools_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle casual queries (greetings, info requests, commit queries) with LLM-based intent classification.
    
    This node uses an LLM to classify the user's intent and route to the appropriate handler:
    - Greetings ("hi", "hello")
    - Capabilities ("what can you do?")
    - Repository listings ("show repos")
    - Environment info ("show my environments")
    - Commit queries ("recent commits on X")
    - Other (general questions)
    
    Input: user_query, workspace_id, context
    Output: final_report (the conversational response)
    """
    logger.info("NODE: conversational_node")
    
    try:
        query = state["user_query"]
        workspace_id = state.get("workspace_id")
        service_mapping = state.get("context", {}).get("service_repo_mapping", {})
        
        # ================================================================
        # LLM-based intent classification (no regex!)
        # ================================================================
        from app.services.rca.prompts import CONVERSATIONAL_INTENT_PROMPT_V1
        
        intent_prompt = CONVERSATIONAL_INTENT_PROMPT_V1.format(query=query)
        files = state.get("files", [])
        
        # Prepare messages with multimodal support
        messages = prepare_multimodal_messages(intent_prompt, files)
        
        try:
            intent_response = await asyncio.wait_for(
                llm.ainvoke(messages),
                timeout=15.0
            )
            intent = intent_response.content.strip().lower()
            logger.info(f"LLM classified intent as: {intent}")
        except asyncio.TimeoutError:
            logger.warning("Intent classification timed out, defaulting to 'other'")
            intent = "other"
        except Exception as e:
            logger.error(f"Intent classification failed: {e}, defaulting to 'other'")
            intent = "other"
        
        # ================================================================
        # Handle greetings
        # ================================================================
        if intent == "greeting":
            response = """Hi! I'm an SRE assistant. I can help you:

• **Investigate incidents** – Find root causes of outages, errors, and performance issues
• **Show recent commits** – View recent code changes in any repository
• **List repositories** – See all available services and repos in your workspace
• **Answer questions** – Get information about your infrastructure

What would you like to know?"""
            
            logger.info("Responded to greeting")
            return {
                "final_report": response,
                "intermediate_steps": state.get("intermediate_steps", []),
            }
        
        # ================================================================
        # Handle capabilities queries
        # ================================================================
        if intent == "capabilities":
            response = """I can help you with:

**Incident Investigation:**
• Analyze production issues (errors, outages, slowness)
• Trace root causes through logs, metrics, and code
• Identify which service and commit caused the problem
• Provide actionable next steps and prevention measures

**Code & Repository Information:**
• Show recent commits for any repository
• List all available repositories in your workspace
• Read code files to understand service dependencies

**Infrastructure Insights:**
• View service logs and metrics
• Understand service-to-service dependencies
• Track deployments and changes

Just ask me a question or describe an issue you're facing!"""
            
            logger.info("Responded to capabilities query")
            return {
                "final_report": response,
                "intermediate_steps": state.get("intermediate_steps", []),
            }
        
        # ================================================================
        # Handle repository listing
        # ================================================================
        if intent == "list_repositories":
            if service_mapping:
                repos = list(set(service_mapping.values()))  # Deduplicate
                response = f"**Available repositories in your workspace:**\n\n"
                response += "\n".join([f"• `{repo}`" for repo in sorted(repos)])
                response += f"\n\n*Total: {len(repos)} repositories*"
            else:
                response = "No repositories found in your workspace yet. Make sure your GitHub integration is configured."
            
            logger.info(f"Listed {len(service_mapping)} repositories")
            return {
                "final_report": response,
                "intermediate_steps": state.get("intermediate_steps", []),
            }
        
        # ================================================================
        # Handle environment info queries
        # ================================================================
        if intent == "environment_info":
            environment_context = get_environment_context(state)
            environments = environment_context.get("environments", [])
            default_env_name = environment_context.get("default_environment")
            deployed_commits = environment_context.get("deployed_commits", {})
            
            response = "**Workspace Information:**\n\n"
            
            # Show service mapping
            if service_mapping:
                response += "**🔗 Service → Repository Mapping:**\n"
                for service, repo in sorted(service_mapping.items()):
                    response += f"• `{service}` → `{repo}`\n"
                response += f"\n*Total: {len(service_mapping)} services mapped*\n\n"
            else:
                response += "**Services:** No service mapping found\n\n"
            
            # Show environments
            if environments:
                response += f"**🌍 Environments:** ({len(environments)} total)\n"
                for env in environments:
                    env_name = env.get("name", "Unknown")
                    is_default = " ⭐ (default)" if env_name == default_env_name else ""
                    response += f"• `{env_name}`{is_default}\n"
                response += "\n"
            else:
                response += "**Environments:** No environments configured\n\n"
            
            # Show deployed commits
            if deployed_commits:
                response += "**📦 Deployed Commits by Environment:**\n"
                for env_name, commits in deployed_commits.items():
                    if commits:
                        response += f"\n*{env_name}:*\n"
                        for repo_name, sha in commits.items():
                            short_sha = sha[:7] if sha else "unknown"
                            response += f"  • `{repo_name}` @ `{short_sha}`\n"
            else:
                response += "**Deployed Commits:** No deployments tracked yet\n"
            
            logger.info(f"Showed environment info: {len(environments)} envs, {len(service_mapping)} services, {sum(len(c) for c in deployed_commits.values())} deployments")
            return {
                "final_report": response,
                "intermediate_steps": state.get("intermediate_steps", []),
            }
        
        # ================================================================
        # Handle commit queries
        # ================================================================
        if intent == "commit_query":
            # Use LLM to extract repo name from query instead of regex
            repo_name = None
            
            # Try to match repo/service names mentioned in the query
            query_lower = query.lower()
            for service, repo in service_mapping.items():
                if repo.lower() in query_lower or service.lower() in query_lower:
                    repo_name = repo
                    break
            
            # If no specific repo mentioned, check if "recent commits" is a general request
            if not repo_name:
                # Try to use the first repo as a default
                if service_mapping:
                    repos = list(service_mapping.values())
                    response = "I need to know which repository you'd like to see commits for. Available repositories:\n\n"
                    response += "\n".join([f"• `{repo}`" for repo in repos])
                    response += "\n\nPlease ask: \"show recent commits on [repo_name]\""
                else:
                    response = "No repositories configured in your workspace. Please set up your GitHub integration first."
                
                return {
                    "final_report": response,
                    "intermediate_steps": state.get("intermediate_steps", []),
                }
            
            # Try to fetch commits using the tool
            try:
                if "get_branch_recent_commits_tool" in tools_dict:
                    commits_tool = tools_dict["get_branch_recent_commits_tool"]
                    logger.info(f"📜 Fetching recent commits for repo: {repo_name}")
                    
                    # Use helper to resolve default branch and fetch commits
                    commits_result, successful_branch, attempted_branches = await resolve_default_branch_and_fetch_commits(
                        commits_tool, workspace_id, repo_name, first=10
                    )
                    
                    # Parse and format commits
                    if commits_result:
                        # Successfully fetched commits
                        response = f"**Recent commits in `{repo_name}` ({successful_branch} branch):**\n\n"
                        
                        # Handle string response
                        if isinstance(commits_result, str):
                            response += commits_result
                        else:
                            response += "Found commits:\n" + str(commits_result)[:800]
                        
                        logger.info(f"✅ Successfully fetched commits from {successful_branch}")
                    else:
                        # All branches failed - parse error and provide actionable feedback
                        error_info = parse_tool_error("", "get_branch_recent_commits_tool", f"repo '{repo_name}'")
                        response = f"⚠️ {error_info['user_message']}\n\n"
                        response += f"Tried branches: {', '.join(attempted_branches)}\n\n"
                        response += "You can view commits by:\n"
                        response += f"• Opening https://github.com/[owner]/{repo_name}/commits\n"
                        response += f"• Running `git log -n 10 --oneline` in your local clone"
                else:
                    response = f"⚠️ Commit fetching tool not available (GitHub integration required).\n\n"
                    response += f"To view recent commits for `{repo_name}`:\n"
                    response += "• Open the repository in GitHub/GitLab\n"
                    response += "• Run `git log -n 10 --oneline` locally"
                
            except Exception as tool_error:
                logger.error(f"Error fetching commits: {tool_error}", exc_info=True)
                error_info = parse_tool_error(str(tool_error), "get_branch_recent_commits_tool", f"repo '{repo_name}'")
                response = f"⚠️ {error_info['user_message']}\n\n"
                response += f"**Suggestion:** {error_info['actionable']}"
            
            return {
                "final_report": response,
                "intermediate_steps": state.get("intermediate_steps", []),
            }
        
        # ================================================================
        # Default response for "other" or unrecognized intents
        # ================================================================
        logger.info(f"Unhandled intent '{intent}', responding with default message")
        response = """I can help you with:

• **Incident investigations** – Describe any errors or issues you're seeing
• **Recent commits** – Ask "show recent commits on [repo_name]"
• **Repository list** – Ask "show all repositories"
• **Environment info** – Ask "show my environments and services"

What would you like to know?"""
        return {
            "final_report": response,
            "intermediate_steps": state.get("intermediate_steps", []),
        }
        
    except Exception as e:
        logger.error(f"Error in conversational_node: {e}", exc_info=True)
        
        # Fallback friendly response
        query_lower = query.lower() if query else ""
        if any(greeting in query_lower for greeting in ["hi", "hello", "hey"]):
            response = "Hi! I'm your SRE assistant. I can help investigate incidents, show commits, and answer questions about your services. What do you need?"
        else:
            response = f"I'm here to help, but encountered an issue: {str(e)}\n\nPlease try rephrasing your question or ask me what I can help with."
        
        return {
            "final_report": response,
            "error": str(e),
        }


# ============================================================================
# Node 1: PARSE_QUERY
# ============================================================================

async def parse_query_node(state: RCAStateV2, llm: BaseChatModel) -> Dict[str, Any]:
    """
    Extract structured information from user query (INCIDENT ONLY - casual queries don't reach here).
    
    Input: user_query
    Output: primary_service, symptoms, incident_type
    """
    logger.info("NODE: parse_query_node")
    
    try:
        query = state["user_query"]
        service_mapping = state.get("context", {}).get("service_repo_mapping", {})
        
        # Format available services for context
        available_services = ""
        if service_mapping:
            available_services = "\n## AVAILABLE SERVICES:\n\nYour workspace has these services:\n"
            available_services += "\n".join([f"- `{service}`" for service in service_mapping.keys()])
            available_services += "\n\nIf the user mentions one of these services, use the exact name from the list above.\n"
        
        prompt = PARSE_QUERY_PROMPT_V1.format(
            available_services=available_services,
            query=query,
        )
        files = state.get("files", [])
        
        # Prepare messages with multimodal support
        messages = prepare_multimodal_messages(prompt, files)
        
        # Add timeout to LLM call
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=45.0
        )
        content = response.content.strip()
        
        logger.info(f"Parse response: {content}")
        
        # Parse response
        primary_service = extract_field(content, "PRIMARY_SERVICE")
        symptoms_str = extract_field(content, "SYMPTOMS")
        incident_type = extract_field(content, "TYPE")
        
        # Split symptoms
        symptoms = [s.strip() for s in symptoms_str.split(",") if s.strip()]
        
        # Add to intermediate steps
        intermediate_steps = state.get("intermediate_steps", [])
        intermediate_steps.append({
            "step": "parse",
            "result": {
                "primary_service": primary_service,
                "symptoms": symptoms,
                "incident_type": incident_type
            }
        })
        
        return {
            "primary_service": primary_service,
            "symptoms": symptoms,
            "incident_type": incident_type,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in parse_query_node: {e}")
        return {
            "primary_service": "unknown",
            "symptoms": ["error parsing query"],
            "incident_type": "availability",
            "error": str(e),
        }


# ============================================================================
# Node 2: PLAN
# ============================================================================

async def plan_node(state: RCAStateV2) -> Dict[str, Any]:
    """
    Create investigation strategy.
    
    Input: primary_service, incident_type, context
    Output: services_to_check, tools_to_use
    """
    logger.info("NODE: plan_node")
    
    try:
        primary_service = state.get("primary_service", "unknown")
        incident_type = state.get("incident_type", "availability")
        service_mapping = state.get("context", {}).get("service_repo_mapping", {})
        
        # COMPREHENSIVE: Check ALL services to find dependencies and root causes
        # Even if user mentions one service, the issue could be in ANY upstream service
        services_to_check = []
        
        if not service_mapping:
            logger.warning("⚠️ No service_repo_mapping provided! Cannot investigate services.")
            services_to_check = [primary_service] if primary_service != "unknown" else []
        elif primary_service and primary_service != "unknown":
            # CRITICAL: Always check ALL services, not just the primary one
            # The primary service is often just a VICTIM, not the culprit
            logger.info(f"Primary service (reported issue): {primary_service}")
            logger.info(f"Available services in workspace: {list(service_mapping.keys())}")
            
            # Start with primary service
            services_to_check.append(primary_service)
            
            # Add ALL other services (they could be upstream dependencies)
            for service in service_mapping.keys():
                if service not in services_to_check:
                    services_to_check.append(service)
            
            logger.info(f"✅ Will check ALL {len(services_to_check)} services to find root cause")
        else:
            # If no primary service identified, check ALL services
            services_to_check = list(service_mapping.keys())
            logger.info(f"No specific service mentioned - checking all {len(services_to_check)} services")
        
        logger.info(f"📋 Investigation plan: {services_to_check}")
        
        # Determine tools based on incident type
        # IMPORTANT: Always include "code" to discover service dependencies
        if incident_type == "availability":
            tools_to_use = ["code", "commits", "logs"]
        elif incident_type == "performance":
            tools_to_use = ["code", "metrics", "logs", "commits"]
        else:
            # Default: check everything
            tools_to_use = ["code", "logs", "metrics", "commits"]
        
        logger.info(f"Plan: Check {len(services_to_check)} services with tools {tools_to_use}")
        
        # Add to intermediate steps
        intermediate_steps = state.get("intermediate_steps", [])
        intermediate_steps.append({
            "step": "plan",
            "result": {
                "services_to_check": services_to_check,
                "tools_to_use": tools_to_use
            }
        })
        
        return {
            "services_to_check": services_to_check,
            "tools_to_use": tools_to_use,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in plan_node: {e}")
        return {
            "services_to_check": [],
            "tools_to_use": ["logs"],
            "error": str(e),
        }


# ============================================================================
# Node 3: INVESTIGATE
# ============================================================================

async def investigate_node(
    state: RCAStateV2,
    tools_dict: Dict[str, Any],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Collect evidence with summarization.
    
    Input: services_to_check, tools_to_use
    Output: logs_summary, metrics_summary, code_findings, commit_findings
    """
    logger.info("NODE: investigate_node")
    
    try:
        services = state.get("services_to_check", [])
        tools_to_use = state.get("tools_to_use", [])
        workspace_id = state.get("workspace_id")
        user_query = state.get("user_query", "")
        service_mapping = state.get("context", {}).get("service_repo_mapping", {})
        
        # Extract environment context
        environment_context = get_environment_context(state)
        target_environment = determine_target_environment(user_query, environment_context)
        
        logs_summary = {}
        metrics_summary = {}
        code_findings = {}
        commit_findings = {}
        
        # Investigate each service (sequential for now - parallel would be complex)
        for service in services:
            logger.info(f"Investigating service: {service}")
            
            # 1. Check logs - try all available integrations
            if "logs" in tools_to_use:
                logs_fetched = False
                try:
                    # Try Grafana logs first (most common)
                    if "fetch_logs_tool" in tools_dict:
                        logger.info(f"📋 Checking logs for {service} (Grafana)")
                        logs_tool = tools_dict["fetch_logs_tool"]
                        # Try to discover service_label_key first, fallback to common values
                        service_label_key = "service_name"  # Default, can be discovered via get_labels_tool
                        logs_result = await asyncio.wait_for(
                            logs_tool.ainvoke({
                                "service_name": service,
                                "workspace_id": workspace_id,
                                "service_label_key": service_label_key,
                                "search_term": "error OR fail OR exception",
                                "start": "now-2h",
                                "end": "now",
                                "limit": 100,
                            }),
                            timeout=30.0
                        )
                        if logs_result and isinstance(logs_result, str) and len(logs_result) > 50:
                            if len(logs_result) > 500:
                                summary = await summarize_logs(logs_result, llm)
                                logs_summary[service] = summary
                                logger.info(f"✅ Logs summary for {service} (Grafana): {summary[:100]}...")
                            else:
                                logs_summary[service] = logs_result
                            logs_fetched = True
                    
                    # Fallback to New Relic
                    elif "search_newrelic_logs_tool" in tools_dict:
                        logger.info(f"📋 Checking logs for {service} (New Relic)")
                        logs_tool = tools_dict["search_newrelic_logs_tool"]
                        logs_result = await asyncio.wait_for(
                            logs_tool.ainvoke({
                            "workspace_id": workspace_id,
                            "search_query": f"appName:{service} error OR fail OR exception",
                            "start_hours_ago": 2,
                            "limit": 100,
                            }),
                            timeout=30.0
                        )
                        if logs_result and len(str(logs_result)) > 100:
                            summary = await summarize_logs(str(logs_result), llm)
                            logs_summary[service] = summary
                            logger.info(f"✅ Logs summary for {service} (New Relic): {summary[:100]}...")
                        else:
                            logs_summary[service] = logs_result
                        logs_fetched = True
                    
                    # Fallback to Datadog
                    elif "search_datadog_logs_tool" in tools_dict:
                        logger.info(f"📋 Checking logs for {service} (Datadog)")
                        logs_tool = tools_dict["search_datadog_logs_tool"]
                        logs_result = await asyncio.wait_for(
                            logs_tool.ainvoke({
                                "workspace_id": workspace_id,
                                "service": service,
                                "query": f"service:{service} (error OR fail OR exception)",
                                "start_time": "2h",
                                "limit": 100,
                            }),
                            timeout=30.0
                        )
                        if logs_result and len(str(logs_result)) > 100:
                            summary = await summarize_logs(str(logs_result), llm)
                            logs_summary[service] = summary
                            logger.info(f"✅ Logs summary for {service} (Datadog): {summary[:100]}...")
                        else:
                            logs_summary[service] = logs_result
                        logs_fetched = True
                    
                    # Fallback to CloudWatch
                    elif "search_cloudwatch_logs_tool" in tools_dict:
                        logger.info(f"📋 Checking logs for {service} (CloudWatch)")
                        logs_tool = tools_dict["search_cloudwatch_logs_tool"]
                        logs_result = await asyncio.wait_for(
                            logs_tool.ainvoke({
                                "workspace_id": workspace_id,
                                "log_group_name": f"/aws/service/{service}",
                                "filter_pattern": "error OR fail OR exception",
                                "start_time": "2h",
                                "limit": 100,
                            }),
                            timeout=30.0
                        )
                        if logs_result and len(str(logs_result)) > 100:
                            summary = await summarize_logs(str(logs_result), llm)
                            logs_summary[service] = summary
                            logger.info(f"✅ Logs summary for {service} (CloudWatch): {summary[:100]}...")
                        else:
                            logs_summary[service] = logs_result
                        logs_fetched = True
                    
                    if not logs_fetched:
                        logger.warning(f"⚠️ No logs tool available for {service} (need Grafana, New Relic, Datadog, or CloudWatch integration)")
                        logs_summary[service] = "No logs tool available - integrate Grafana, New Relic, Datadog, or CloudWatch to collect logs"
                            
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Logs fetch timed out for {service} (30s)")
                    logs_summary[service] = "Logs fetch timed out after 30 seconds"
                except Exception as e:
                    logger.error(f"Error fetching logs for {service}: {e}")
                    logs_summary[service] = f"Error: {str(e)}"
            
            # 2. Check metrics - try all available integrations
            if "metrics" in tools_to_use:
                metrics_fetched = False
                try:
                    # Try Grafana metrics first (most common)
                    if "fetch_http_latency_tool" in tools_dict or "fetch_cpu_metrics_tool" in tools_dict:
                        logger.info(f"📊 Checking metrics for {service} (Grafana)")
                        metrics_results = []
                        
                        # Fetch HTTP latency (most important for performance issues)
                        if "fetch_http_latency_tool" in tools_dict:
                            latency_tool = tools_dict["fetch_http_latency_tool"]
                            latency_result = await asyncio.wait_for(
                                latency_tool.ainvoke({
                                    "workspace_id": workspace_id,
                                    "service_name": service,
                                    "start_time": "now-2h",
                                    "end_time": "now",
                                    "step": "60s",
                                }),
                                timeout=30.0
                            )
                            if latency_result:
                                metrics_results.append(f"HTTP Latency: {latency_result}")
                        
                        # Fetch CPU metrics
                        if "fetch_cpu_metrics_tool" in tools_dict:
                            cpu_tool = tools_dict["fetch_cpu_metrics_tool"]
                            cpu_result = await asyncio.wait_for(
                                cpu_tool.ainvoke({
                                    "workspace_id": workspace_id,
                                    "service_name": service,
                                    "start_time": "now-2h",
                                    "end_time": "now",
                                    "step": "60s",
                                }),
                                timeout=30.0
                            )
                            if cpu_result:
                                metrics_results.append(f"CPU: {cpu_result}")
                        
                        # Fetch error rate metrics
                        if "fetch_metrics_tool" in tools_dict:
                            error_tool = tools_dict["fetch_metrics_tool"]
                            error_result = await asyncio.wait_for(
                                error_tool.ainvoke({
                                    "metric_type": "errors",
                                    "workspace_id": workspace_id,
                                    "service_name": service,
                                    "start_time": "now-2h",
                                    "end_time": "now",
                                    "step": "60s",
                                }),
                                timeout=30.0
                            )
                            if error_result:
                                metrics_results.append(f"Errors: {error_result}")
                        
                        if metrics_results:
                            combined_metrics = "\n".join(metrics_results)
                            metrics_summary[service] = summarize_metrics({"raw": combined_metrics})
                            logger.info(f"✅ Metrics for {service} (Grafana): {metrics_summary[service][:100]}...")
                            metrics_fetched = True
                    
                    # Fallback to New Relic
                    elif "query_newrelic_metrics_tool" in tools_dict:
                        logger.info(f"📊 Checking metrics for {service} (New Relic)")
                        metrics_tool = tools_dict["query_newrelic_metrics_tool"]
                        metrics_result = await asyncio.wait_for(
                            metrics_tool.ainvoke({
                            "workspace_id": workspace_id,
                            "nrql_query": f"SELECT average(duration), count(*), percentage(count(*), WHERE error IS true) FROM Transaction WHERE appName = '{service}' SINCE 2 hours ago",
                            }),
                            timeout=30.0
                        )
                        metrics_summary[service] = summarize_metrics({"raw": metrics_result})
                        logger.info(f"✅ Metrics for {service} (New Relic): {metrics_summary[service][:100]}...")
                        metrics_fetched = True
                    
                    # Fallback to Datadog
                    elif "query_datadog_metrics_tool" in tools_dict:
                        logger.info(f"📊 Checking metrics for {service} (Datadog)")
                        metrics_tool = tools_dict["query_datadog_metrics_tool"]
                        metrics_result = await asyncio.wait_for(
                            metrics_tool.ainvoke({
                                "workspace_id": workspace_id,
                                "query": f"avg:service.duration{{service:{service}}}",
                                "start_time": "2h",
                                "end_time": "now",
                            }),
                            timeout=30.0
                        )
                        metrics_summary[service] = summarize_metrics({"raw": str(metrics_result)})
                        logger.info(f"✅ Metrics for {service} (Datadog): {metrics_summary[service][:100]}...")
                        metrics_fetched = True
                    
                    # Fallback to CloudWatch
                    elif "list_cloudwatch_metrics_tool" in tools_dict:
                        logger.info(f"📊 Checking metrics for {service} (CloudWatch)")
                        metrics_tool = tools_dict["list_cloudwatch_metrics_tool"]
                        metrics_result = await asyncio.wait_for(
                            metrics_tool.ainvoke({
                                "workspace_id": workspace_id,
                                "namespace": f"AWS/{service}",
                                "metric_name": "Duration",
                                "start_time": "2h",
                                "end_time": "now",
                            }),
                            timeout=30.0
                        )
                        metrics_summary[service] = summarize_metrics({"raw": str(metrics_result)})
                        logger.info(f"✅ Metrics for {service} (CloudWatch): {metrics_summary[service][:100]}...")
                        metrics_fetched = True
                    
                    if not metrics_fetched:
                        logger.warning(f"⚠️ No metrics tool available for {service} (need Grafana, New Relic, Datadog, or CloudWatch integration)")
                        metrics_summary[service] = "No metrics tool available - integrate Grafana, New Relic, Datadog, or CloudWatch to collect performance metrics"
                        
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Metrics fetch timed out for {service} (30s)")
                    metrics_summary[service] = "Metrics fetch timed out after 30 seconds"
                except Exception as e:
                    logger.error(f"Error fetching metrics for {service}: {e}")
                    metrics_summary[service] = f"Error: {str(e)}"
            
            # 3. Check code (CRITICAL for finding issues in code)
            if "code" in tools_to_use:
                files_tried = []
                try:
                    # Map service name to repository name
                    repo_name = service_mapping.get(service)
                    if not repo_name:
                        logger.warning(f"⚠️ Service '{service}' not in mapping, trying fallback")
                        # Auto-discover best matching repo if not in mapping
                        if "list_repositories_graphql_tool" in tools_dict:
                            repo_name, confidence, method = await discover_best_matching_repo(
                                tools_dict["list_repositories_graphql_tool"],
                                workspace_id,
                                service,
                                service_mapping
                            )
                            logger.info(f"   Auto-discovered repo '{repo_name}' for service '{service}' (confidence: {confidence:.2f})")
                        else:
                            repo_name = service
                    
                    logger.info(f"📖 Reading code from repository: {repo_name} (service: {service})")
                    
                    # Get deployed commit SHA for this repo if environment context is available
                    deployed_commit_sha = None
                    if target_environment:
                        # Try to get full repo name (owner/repo-name format)
                        repo_full_name = repo_name
                        if "/" not in repo_name and service_mapping:
                            # Try to find full name from service mapping
                            for svc, mapped_repo in service_mapping.items():
                                if mapped_repo == repo_name or mapped_repo.endswith(f"/{repo_name}"):
                                    repo_full_name = mapped_repo
                                    break
                        
                        deployed_commit_sha = get_deployed_commit_sha(
                            repo_full_name,
                            target_environment,
                            environment_context
                        )
                        
                        if deployed_commit_sha:
                            logger.info(f"   Using deployed commit SHA: {deployed_commit_sha[:8]}... (environment: {target_environment})")
                        else:
                            logger.info(f"   No deployed commit found for {repo_full_name} in {target_environment}, using HEAD")
                    
                    # Prefer download_file_tool (supports ref parameter) over read_repository_file_tool
                    has_download_tool = "download_file_tool" in tools_dict
                    has_tree_tool = "get_repository_tree_tool" in tools_dict
                    has_read_tool = "read_repository_file_tool" in tools_dict
                    
                    if has_tree_tool and (has_download_tool or has_read_tool):
                        tree_tool = tools_dict["get_repository_tree_tool"]
                        # Use download_file_tool if available (supports ref parameter for commit SHAs)
                        code_tool = tools_dict.get("download_file_tool") or tools_dict.get("read_repository_file_tool")
                        use_download_tool = has_download_tool
                        
                        # Null check for code_tool
                        if not code_tool:
                            logger.error(f"⚠️ Code tool not found despite has_download_tool={has_download_tool}, has_read_tool={has_read_tool}")
                            code_findings[service] = "Code reading tool unavailable"
                            continue
                        
                        logger.info(f"   Discovering files in {repo_name} repository...")
                        
                        # Get repository tree to discover actual files
                        try:
                            # Resolve default branch first (don't assume HEAD/main/master!)
                            default_branch = None
                            if "get_branch_recent_commits_tool" in tools_dict:
                                commits_tool = tools_dict["get_branch_recent_commits_tool"]
                                _, default_branch, _ = await resolve_default_branch_and_fetch_commits(
                                    commits_tool, workspace_id, repo_name, first=1
                                )
                            
                            # Use deployed commit SHA if available, otherwise use resolved default branch
                            if deployed_commit_sha:
                                tree_expression = f"{deployed_commit_sha}:"
                                logger.debug(f"   Using deployed commit SHA: {deployed_commit_sha[:8]}...")
                            elif default_branch:
                                tree_expression = f"{default_branch}:"
                                logger.debug(f"   Using resolved default branch: {default_branch}")
                            else:
                                # Last resort: try HEAD (but log warning)
                                tree_expression = "HEAD:"
                                logger.warning(f"   Could not resolve default branch, trying HEAD (may fail)")
                            
                            tree_result = await tree_tool.ainvoke({
                                "workspace_id": workspace_id,
                                "repo_name": repo_name,
                                "expression": tree_expression,  # Use expression parameter (supports commit SHA or branch)
                            })
                            
                            # Extract ALL filenames from tree (don't assume extensions!)
                            if tree_result and "Error" not in str(tree_result):
                                tree_str = str(tree_result)
                                
                                # Extract ALL files from tree (match any file path, not just code extensions)
                                # Pattern: 📄 filename.ext (blob) or 📁 dirname (tree)
                                all_files_raw = re.findall(r'📄\s+([^\s(]+)', tree_str)
                                
                                # Filter to code files (but be flexible - include common config files too)
                                code_extensions = {'.py', '.js', '.go', '.java', '.ts', '.rb', '.cpp', '.c', '.rs', '.php', '.swift', '.kt'}
                                config_patterns = ['docker-compose', 'Dockerfile', 'package', 'requirements', 'go.mod', 'pom.xml', 'yaml', 'yml', 'json', 'toml', 'ini', 'conf']
                                
                                all_files = []
                                for f in all_files_raw:
                                    # Include files with code extensions OR common config file patterns
                                    has_code_ext = any(f.endswith(ext) for ext in code_extensions)
                                    has_config_pattern = any(pattern in f.lower() for pattern in config_patterns)
                                    
                                    if has_code_ext or has_config_pattern:
                                        all_files.append(f)
                                
                                # Use smart ranking helper
                                files_to_try = rank_code_files_by_relevance(all_files, service)
                                
                                logger.info(f"   Found {len(all_files)} code/config files, will read ALL of them")
                                if files_to_try:
                                    logger.info(f"   Top candidates: {files_to_try[:10]}")
                            else:
                                # Fallback: try to find files by scanning (no hardcoded names)
                                logger.warning(f"   Could not get repo tree, will try to discover files")
                                files_to_try = []  # Empty - will be handled by error case
                        
                        except Exception as tree_error:
                            # Fallback: tree discovery failed
                            error_info = parse_tool_error(str(tree_error), "get_repository_tree_tool", f"repo '{repo_name}'")
                            logger.warning(f"   Tree discovery failed: {error_info['user_message']}")
                            files_to_try = []  # Empty - will be handled by error case
                        
                        # Try reading the discovered/ranked files - READ ALL relevant files, not just first!
                        code_found = False
                        code_summaries = []
                        files_successfully_read = []
                        
                        # Simple approach: Read ALL files in ranked order (no hardcoding)
                        files_to_read = files_to_try  # Use ranking from rank_code_files_by_relevance
                        
                        logger.info(f"   📖 Reading {len(files_to_read)} files (main files first)")
                        
                        for file_path in files_to_read:
                            try:
                                logger.info(f"   Reading: {file_path}")
                                tool_params = {
                                    "workspace_id": workspace_id,
                                    "repo_name": repo_name,
                                    "file_path": file_path,
                                }
                                
                                if use_download_tool and deployed_commit_sha:
                                    tool_params["ref"] = deployed_commit_sha
                                
                                code_result = await asyncio.wait_for(
                                    code_tool.ainvoke(tool_params),
                                    timeout=30,
                                )
                                
                                if code_result and "Error" not in str(code_result) and "not found" not in str(code_result).lower():
                                    # Analyze the full file (no truncation)
                                    summary = await extract_key_info_from_code(str(code_result), llm)
                                    code_summaries.append(f"{file_path}: {summary}")
                                    files_successfully_read.append(file_path)
                                    logger.info(f"✅ Analyzed {file_path}")
                                    code_found = True
                            except Exception as e:
                                logger.warning(f"   Error reading {file_path}: {str(e)[:100]}")
                                continue
                        
                        if code_found and code_summaries:
                            code_findings[service] = "\n".join(code_summaries)
                            logger.info(f"✅ Read {len(files_successfully_read)} files for {service}")
                        elif not code_found:
                            logger.warning(f"⚠️ No accessible code files found for {service} (tried: {', '.join(files_tried)})")
                            code_findings[service] = f"Repository '{repo_name}' found but couldn't access code files (tried: {', '.join(files_tried[:3])})"
                    else:
                        logger.warning(f"⚠️ No code tools available (need GitHub integration with tree/read capabilities)")
                        code_findings[service] = "Code tools not available - GitHub integration required"
                    
                    # Log environment context usage
                    if target_environment and deployed_commit_sha:
                        logger.info(f"✅ Code read using deployed commit from environment '{target_environment}'")
                    elif target_environment:
                        logger.warning(f"⚠️ Environment '{target_environment}' specified but no deployed commit found - using HEAD")
                                
                except Exception as e:
                    error_info = parse_tool_error(str(e), "code_investigation", f"service '{service}'")
                    logger.error(f"Error reading code for {service}: {error_info['user_message']}")
                    code_findings[service] = f"Error: {error_info['user_message']}"
            
            # 4. Check commits
            if "commits" in tools_to_use:
                try:
                    # Auto-discover best matching repo if not in mapping
                    if "list_repositories_graphql_tool" in tools_dict:
                        repo_name, confidence, method = await discover_best_matching_repo(
                            tools_dict["list_repositories_graphql_tool"],
                            workspace_id,
                            service,
                            service_mapping
                        )
                        if method != "mapping":
                            logger.info(f"   Auto-discovered repo '{repo_name}' for service '{service}' (method: {method}, confidence: {confidence:.2f})")
                    else:
                        repo_name = service_mapping.get(service) or service
                    
                    if "get_branch_recent_commits_tool" in tools_dict:
                        commits_tool = tools_dict["get_branch_recent_commits_tool"]
                        logger.info(f"📜 Checking recent commits in {repo_name} repository")
                        
                        # Use helper to resolve default branch and fetch commits
                        commits_result, successful_branch, attempted_branches = await resolve_default_branch_and_fetch_commits(
                            commits_tool, workspace_id, repo_name, first=5
                        )
                        
                        # Summarize commits if found
                        if commits_result:
                            commit_findings[service] = summarize_commits(commits_result)
                            logger.info(f"✅ Commits for {service} from {successful_branch}: {len(str(commits_result))} chars")
                        else:
                            error_info = parse_tool_error("", "get_branch_recent_commits_tool", f"repo '{repo_name}'")
                            logger.warning(f"⚠️ {error_info['user_message']} (tried: {', '.join(attempted_branches)})")
                            commit_findings[service] = f"Could not fetch commits (tried branches: {', '.join(attempted_branches)})"
                    else:
                        logger.warning(f"⚠️ No commit fetching tool available (need GitHub integration)")
                        commit_findings[service] = "Commit tool not available - GitHub integration required"
                        
                except Exception as e:
                    error_info = parse_tool_error(str(e), "get_branch_recent_commits_tool", f"service '{service}'")
                    logger.error(f"Error fetching commits for {service}: {error_info['user_message']}")
                    commit_findings[service] = f"Error: {error_info['user_message']}"
        
        # Add to intermediate steps with detailed telemetry
        intermediate_steps = state.get("intermediate_steps", [])
        
        # Build telemetry summary
        telemetry = {
            "services_investigated": services,
            "tools_attempted": tools_to_use,
            "data_collected": {
                "logs": len(logs_summary),
                "metrics": len(metrics_summary),
                "code": len(code_findings),
                "commits": len(commit_findings),
            },
            "tool_availability": {
                "logs_tool": "search_newrelic_logs_tool" in tools_dict,
                "metrics_tool": "query_newrelic_metrics_tool" in tools_dict,
                "code_tools": "read_repository_file_tool" in tools_dict and "get_repository_tree_tool" in tools_dict,
                "commits_tool": "get_branch_recent_commits_tool" in tools_dict,
                "repo_discovery_tool": "list_repositories_graphql_tool" in tools_dict,
            },
            "skipped_tools": []
        }
        
        # Identify which tools were skipped and why
        if "logs" in tools_to_use and not logs_summary:
            if "search_newrelic_logs_tool" not in tools_dict:
                telemetry["skipped_tools"].append({"tool": "logs", "reason": "tool_not_available"})
            else:
                telemetry["skipped_tools"].append({"tool": "logs", "reason": "collection_failed"})
        
        if "metrics" in tools_to_use and not metrics_summary:
            if "query_newrelic_metrics_tool" not in tools_dict:
                telemetry["skipped_tools"].append({"tool": "metrics", "reason": "tool_not_available"})
            else:
                telemetry["skipped_tools"].append({"tool": "metrics", "reason": "collection_failed"})
        
        if "code" in tools_to_use and not code_findings:
            if "read_repository_file_tool" not in tools_dict:
                telemetry["skipped_tools"].append({"tool": "code", "reason": "tool_not_available"})
            else:
                telemetry["skipped_tools"].append({"tool": "code", "reason": "files_not_accessible"})
        
        if "commits" in tools_to_use and not commit_findings:
            if "get_branch_recent_commits_tool" not in tools_dict:
                telemetry["skipped_tools"].append({"tool": "commits", "reason": "tool_not_available"})
            else:
                telemetry["skipped_tools"].append({"tool": "commits", "reason": "branch_not_found"})
        
        intermediate_steps.append({
            "step": "investigate",
            "result": {
                "logs_summary": list(logs_summary.keys()),
                "metrics_summary": list(metrics_summary.keys()),
                "code_findings": list(code_findings.keys()),
                "commit_findings": list(commit_findings.keys()),
            },
            "telemetry": telemetry,
        })
        
        # Log telemetry summary
        logger.info(f"Investigation telemetry: {telemetry['data_collected']} data points collected")
        if telemetry["skipped_tools"]:
            logger.warning(f"Skipped tools: {telemetry['skipped_tools']}")
        
        return {
            "logs_summary": logs_summary,
            "metrics_summary": metrics_summary,
            "code_findings": code_findings,
            "commit_findings": commit_findings,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in investigate_node: {e}")
        return {
            "logs_summary": {},
            "metrics_summary": {},
            "code_findings": {},
            "commit_findings": {},
            "error": str(e),
        }


# ============================================================================
# NEW Node 3B: ITERATIVE_INVESTIGATE (Multi-Level Upstream Tracing)
# ============================================================================

async def iterative_investigate_node(
    state: RCAStateV2,
    tools_dict: Dict[str, Any],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Iterative investigation that follows dependency chains upstream.
    
    This replaces the old plan+investigate pattern with an LLM-driven loop:
    1. Start with primary service (reported issue)
    2. Investigate service (logs, metrics, code, commits)
    3. LLM decides: found root cause? Or investigate upstream?
    4. If upstream: extract dependencies → pick next service → loop
    5. Continue until root cause found or max depth reached
    
    Output:
        - investigation_chain: List of {service, findings, depth, decision}
        - final_decision: ROOT_CAUSE_FOUND | MAX_DEPTH_REACHED | INCONCLUSIVE
        - All aggregated findings for backward compatibility
    """
    logger.info("NODE: iterative_investigate_node (Multi-Level Upstream Tracing)")
    
    try:
        primary_service = state.get("primary_service", "unknown")
        incident_type = state.get("incident_type", "availability")
        workspace_id = state.get("workspace_id")
        user_query = state.get("user_query", "")
        service_mapping = state.get("context", {}).get("service_repo_mapping", {})
        
        # Extract environment context
        environment_context = get_environment_context(state)
        target_environment = determine_target_environment(user_query, environment_context)
        
        # Determine tools based on incident type
        if incident_type == "availability":
            tools_to_use = ["code", "commits", "logs"]
        elif incident_type == "performance":
            tools_to_use = ["code", "metrics", "logs", "commits"]
        elif incident_type == "data":
            tools_to_use = ["code", "logs", "commits"]
        else:
            tools_to_use = ["code", "logs", "metrics", "commits"]
        
        logger.info(f"Tools to use: {tools_to_use}")
        
        # Initialize investigation chain
        investigation_chain = []
        current_service = primary_service
        max_depth = 5  # Prevent infinite loops
        
        # Aggregated findings for backward compatibility
        all_logs_summary = {}
        all_metrics_summary = {}
        all_code_findings = {}
        all_commit_findings = {}
        
        # Main iterative investigation loop
        for depth in range(max_depth):
            logger.info(f"\n{'='*60}")
            logger.info(f"🔍 INVESTIGATION LEVEL {depth + 1}/{max_depth}: `{current_service}`")
            logger.info(f"{'='*60}\n")
            
            # Check if service exists in mapping
            if current_service not in service_mapping and current_service != "unknown":
                logger.warning(f"⚠️ Service '{current_service}' not in mapping. Available: {list(service_mapping.keys())}")
                # Try fuzzy matching
                best_match = None
                best_score = 0
                for mapped_service in service_mapping.keys():
                    score = SequenceMatcher(None, current_service.lower(), mapped_service.lower()).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = mapped_service
                
                if best_match and best_score > 0.6:
                    logger.info(f"   Fuzzy matched '{current_service}' → '{best_match}' (score: {best_score:.2f})")
                    current_service = best_match
                else:
                    logger.error(f"   Could not map service '{current_service}' to any repository. Stopping investigation.")
                    break
            
            # Investigate current service
            findings = await investigate_single_service(
                service=current_service,
                tools_dict=tools_dict,
                llm=llm,
                workspace_id=workspace_id,
                user_query=user_query,
                service_mapping=service_mapping,
                environment_context=environment_context,
                target_environment=target_environment,
                tools_to_use=tools_to_use
            )
            
            # Merge findings into aggregated collections (for backward compatibility)
            all_logs_summary.update(findings.get("logs_summary", {}))
            all_metrics_summary.update(findings.get("metrics_summary", {}))
            all_code_findings.update(findings.get("code_findings", {}))
            all_commit_findings.update(findings.get("commit_findings", {}))
            
            # LLM decides next step
            files = state.get("files", [])
            decision = await llm_decide_next_step(
                services_investigated=investigation_chain,
                current_service=current_service,
                current_findings=findings,
                llm=llm,
                files=files
            )
            
            # Add to investigation chain
            investigation_chain.append({
                "service": current_service,
                "findings": findings,
                "depth": depth,
                "decision": decision
            })
            
            logger.info(f"\n{'='*60}")
            logger.info(f"📊 DECISION for `{current_service}`: {decision['decision']}")
            logger.info(f"   Reasoning: {decision['reasoning']}")
            logger.info(f"   Confidence: {decision['confidence']}%")
            logger.info(f"{'='*60}\n")
            
            # Check decision
            if decision["decision"] == "ROOT_CAUSE_FOUND":
                logger.info(f"✅ ROOT CAUSE FOUND at level {depth + 1}")
                final_decision = "ROOT_CAUSE_FOUND"
                break
            elif decision["decision"] == "INVESTIGATE_UPSTREAM":
                # Extract upstream services to investigate
                upstream_services = decision.get("upstream_services", [])
                
                if not upstream_services:
                    # LLM said investigate upstream but didn't specify services
                    # Try to extract from findings
                    logger.info("   LLM suggested upstream investigation but didn't specify services. Extracting from findings...")
                    files = state.get("files", [])
                    upstream_services = await extract_upstream_dependencies(findings, llm, files=files)
                
                if not upstream_services:
                    logger.warning(f"   No upstream services identified from LLM or extraction.")
                    # Don't give up yet - use fallback strategy below
                    upstream_services = []
                
                if upstream_services:
                    # Pick first upstream service (could be smarter here)
                    next_service = upstream_services[0]
                    logger.info(f"   ⬆️  Moving upstream to: `{next_service}`")
                    
                    # Check if we've already investigated this service (cycle detection)
                    if any(item["service"] == next_service for item in investigation_chain):
                        logger.warning(f"   ⚠️ Cycle detected! Already investigated `{next_service}`. Stopping.")
                        final_decision = "CYCLE_DETECTED"
                        break
                    
                    current_service = next_service
                else:
                    # Fallback: Check all uninvestigated services
                    logger.info(f"   🔄 Using fallback: checking all uninvestigated services")
                    all_services = list(service_mapping.keys())
                    uninvestigated = [s for s in all_services 
                                      if s != current_service 
                                      and not any(item["service"] == s for item in investigation_chain)]
                    
                    if uninvestigated:
                        next_service = uninvestigated[0]
                        logger.info(f"   🔄 Fallback → Investigating `{next_service}` (exhaustive search)")
                        current_service = next_service
                        # Continue loop - don't break!
                    else:
                        # Truly exhausted all services
                        logger.warning(f"   No upstream found and all services checked. Investigation inconclusive.")
                        final_decision = "INCONCLUSIVE"
                        break
            else:
                # INCONCLUSIVE decision from LLM
                logger.warning(f"   LLM decision: INCONCLUSIVE (confidence: {decision['confidence']}%)")
                logger.info(f"   🔄 Using fallback strategy: checking all uninvestigated services")
                
                # Fallback: Check all services in workspace
                all_services = list(service_mapping.keys())
                uninvestigated = [s for s in all_services 
                                  if s != current_service 
                                  and not any(item["service"] == s for item in investigation_chain)]
                
                if uninvestigated:
                    next_service = uninvestigated[0]
                    logger.info(f"   🔄 Fallback → Investigating `{next_service}` (exhaustive search)")
                    current_service = next_service
                    # DON'T break - continue investigating!
                else:
                    # Truly exhausted all services
                    logger.info(f"   ✅ Checked all {len(investigation_chain)} services, no clear root cause found")
                    final_decision = "INCONCLUSIVE"
                    break
        else:
            # Loop exhausted (reached max_depth)
            logger.warning(f"⚠️ Reached maximum investigation depth ({max_depth}). Stopping.")
            final_decision = "MAX_DEPTH_REACHED"
        
        # Log investigation summary
        logger.info(f"\n{'='*60}")
        logger.info(f"📋 INVESTIGATION SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"   Total levels investigated: {len(investigation_chain)}")
        logger.info(f"   Services traced: {[item['service'] for item in investigation_chain]}")
        logger.info(f"   Final decision: {final_decision}")
        logger.info(f"{'='*60}\n")
        
        # Add to intermediate steps
        intermediate_steps = state.get("intermediate_steps", [])
        intermediate_steps.append({
            "step": "iterative_investigate",
            "result": {
                "levels_investigated": len(investigation_chain),
                "services_traced": [item['service'] for item in investigation_chain],
                "final_decision": final_decision,
            }
        })
        
        return {
            # New: full investigation chain for multi-level RCA
            "investigation_chain": investigation_chain,
            "final_decision": final_decision,
            
            # Backward compatibility: aggregated findings
            "logs_summary": all_logs_summary,
            "metrics_summary": all_metrics_summary,
            "code_findings": all_code_findings,
            "commit_findings": all_commit_findings,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in iterative_investigate_node: {e}", exc_info=True)
        return {
            "investigation_chain": [],
            "final_decision": "ERROR",
            "logs_summary": {},
            "metrics_summary": {},
            "code_findings": {},
            "commit_findings": {},
            "error": str(e),
        }


# ============================================================================
# Node 4: ANALYZE_AND_TRACE
# ============================================================================

async def analyze_and_trace_node(
    state: RCAStateV2,
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Find root cause using LLM reasoning.
    
    Supports two modes:
    1. NEW (iterative_investigate_node): Uses investigation_chain to extract multi-level RCA
    2. OLD (plan+investigate nodes): Analyzes aggregated findings at once
    
    Input: All evidence (logs, metrics, code, commits) OR investigation_chain
    Output: root_cause, root_service, root_commit, confidence, (+ victim/intermediate services if available)
    """
    logger.info("NODE: analyze_and_trace_node")
    
    try:
        user_query = state.get("user_query")
        logs_summary = state.get("logs_summary", {})
        metrics_summary = state.get("metrics_summary", {})
        code_findings = state.get("code_findings", {})
        commit_findings = state.get("commit_findings", {})
        
        # Get service mapping for better analysis
        service_mapping = state.get("context", {}).get("service_repo_mapping", {})
        primary_service = state.get("primary_service", "unknown")
        
        # NEW: Check if we have investigation_chain (from iterative_investigate_node)
        investigation_chain = state.get("investigation_chain", [])
        
        if investigation_chain:
            logger.info(f"🔗 Multi-level investigation detected ({len(investigation_chain)} services traced)")
            
            # Extract victim, intermediate, and root services
            victim_service = investigation_chain[0]["service"] if investigation_chain else primary_service
            intermediate_services = [item["service"] for item in investigation_chain[1:-1]] if len(investigation_chain) > 2 else []
            root_service_candidate = investigation_chain[-1]["service"] if investigation_chain else "unknown"
            
            # The last service in the chain should be where the root cause was found
            # Get its decision and findings
            last_investigation = investigation_chain[-1]
            last_decision = last_investigation.get("decision", {})
            last_findings = last_investigation.get("findings", {})
            
            logger.info(f"   Victim: {victim_service}")
            if intermediate_services:
                logger.info(f"   Intermediate: {' → '.join(intermediate_services)}")
            logger.info(f"   Root candidate: {root_service_candidate}")
            
            # Use LLM to analyze the LAST service's findings and extract root cause
            # This is simpler than analyzing everything at once
            last_logs = last_findings.get("logs_summary", {}).get(root_service_candidate, "No logs")
            last_metrics = last_findings.get("metrics_summary", {}).get(root_service_candidate, "No metrics")
            last_code = last_findings.get("code_findings", {}).get(root_service_candidate, "No code")
            last_commits = last_findings.get("commit_findings", {}).get(root_service_candidate, "No commits")
            
            # Simple analysis prompt for the root service
            analysis_prompt = f"""You are analyzing the ROOT CAUSE service in a multi-level investigation.

**Investigation Chain:**
- **Victim service:** `{victim_service}` (where user saw the issue)
{f"- **Intermediate services:** {' → '.join([f'`{s}`' for s in intermediate_services])}" if intermediate_services else ""}
- **Root service:** `{root_service_candidate}` (where the investigation ended)

**Root Service Evidence:**

**Logs:** {str(last_logs)[:1000]}

**Metrics:** {str(last_metrics)[:800]}

**Code:** {str(last_code)[:1200]}

**Recent Commits:** {str(last_commits)[:1000]}

**LLM Investigation Decision:** {last_decision.get('reasoning', 'Root cause found at this service')}

## YOUR TASK:

Analyze the evidence for `{root_service_candidate}` and extract:
1. What is the SPECIFIC root cause? (e.g., "Commit abc123 changed HTTP method from POST to GET")
2. What commit caused it? (commit SHA or "none" if not code-related)
3. How confident are you? (0-100)

## OUTPUT FORMAT:

ROOT_SERVICE: {root_service_candidate}
ROOT_CAUSE: <specific description of what broke>
ROOT_COMMIT: <commit_sha or none>
CONFIDENCE: <0-100>
REASONING: <1-2 sentence explanation>

Respond now:"""
            
            files = state.get("files", [])
            messages = prepare_multimodal_messages(analysis_prompt, files)
            response = await asyncio.wait_for(
                llm.ainvoke(messages),
                timeout=45.0
            )
            content = response.content.strip()
            
            logger.info(f"Multi-level analysis response: {content}")
            
            # Parse response
            root_service = extract_field(content, "ROOT_SERVICE") or root_service_candidate
            root_cause = extract_field(content, "ROOT_CAUSE")
            root_commit = extract_field(content, "ROOT_COMMIT")
            confidence_str = extract_field(content, "CONFIDENCE")
            
            # Parse confidence
            try:
                confidence = float(confidence_str) / 100.0
            except:
                confidence = last_decision.get("confidence", 70) / 100.0
            
            logger.info(f"✅ Multi-level RCA complete:")
            logger.info(f"   Victim: {victim_service} → Root: {root_service}")
            logger.info(f"   Root cause: {root_cause}")
            logger.info(f"   Confidence: {confidence}")
            
            # Add to intermediate steps
            intermediate_steps = state.get("intermediate_steps", [])
            intermediate_steps.append({
                "step": "analyze_trace_multilevel",
                "result": {
                    "victim_service": victim_service,
                    "intermediate_services": intermediate_services,
                    "root_service": root_service,
                    "root_cause": root_cause,
                    "confidence": confidence
                }
            })
            
            return {
                "root_service": root_service,
                "root_cause": root_cause,
                "root_commit": root_commit if root_commit and root_commit != "none" else None,
                "confidence": confidence,
                # NEW: Multi-level RCA fields
                "victim_service": victim_service,
                "intermediate_services": intermediate_services,
                "intermediate_steps": intermediate_steps,
            }
        
        # FALLBACK: Old single-pass analysis (backward compatibility)
        logger.info("Using single-pass analysis (old mode)")
        
        # Extract environment context for reporting
        environment_context = get_environment_context(state)
        target_environment = determine_target_environment(user_query, environment_context)
        
        if target_environment:
            logger.info(f"Analyzing root cause for environment: {target_environment}")
        
        # Format service mapping
        mapping_text = ""
        if service_mapping:
            mapping_text = "Available services and repositories:\n"
            mapping_text += "\n".join([f"- `{service}` → `{repo}`" for service, repo in service_mapping.items()])
        
        # Prepare context for LLM (improved with LC agent's mindset)
        context = f"""You are an expert Site Reliability Engineer performing root cause analysis. Your task is to analyze all collected evidence and identify the ACTUAL root cause of the incident.

## 🔍 INVESTIGATION MINDSET (CRITICAL - READ CAREFULLY)

### Core Principle: THE REPORTED SERVICE IS USUALLY A VICTIM, NOT THE CULPRIT

When a user reports "Service X is broken", Service X is almost always a VICTIM of an upstream dependency failure. Your job is to:
1. Understand what Service X depends on (from code analysis)
2. Trace upstream through the dependency chain
3. Find which upstream service is the actual CULPRIT
4. Identify what changed in the culprit service (commit, config, etc.)

### Investigation Flow Example:
```
User reports: "Can't access data in frontend"
↓
Frontend logs: 404 errors calling api-service
↓
API logs: 405 errors calling auth
↓  
Auth logs: Method Not Allowed (expects POST, got GET)
↓
API code: Uses GET for /verify (wrong!)
↓
API commits: abc1234 changed POST → GET
↓
ROOT CAUSE: api-service commit abc1234 changed HTTP method
```

---

## INVESTIGATION CONTEXT

### USER'S REPORTED ISSUE:
{user_query}

### PRIMARY SERVICE (likely the VICTIM):
{primary_service}

### SERVICE MAPPING:
{mapping_text}

### EVIDENCE COLLECTED:

#### LOGS SUMMARY:
{format_dict_for_context(logs_summary, max_length=2000)}

#### METRICS SUMMARY:
{format_dict_for_context(metrics_summary, max_length=1000)}

#### CODE FINDINGS:
{format_dict_for_context(code_findings, max_length=2000)}

#### RECENT COMMITS:
{format_dict_for_context(commit_findings, max_length=2000)}

---

## SYSTEMATIC ANALYSIS FRAMEWORK

### Step 1: Identify Error Patterns
Look at logs and identify:
- **Error codes**: 404 (missing endpoint), 405 (method mismatch), 401/403 (auth), 500 (internal), 503 (unavailable)
- **Error messages**: "Failed to call X", "Token verification failed", "Connection refused", "Timeout"
- **Timestamps**: When did errors start? Which service had errors FIRST?

### Step 2: Trace Dependencies
From code findings, identify:
- What services does the victim call?
- What are the upstream dependencies?
- What endpoints and HTTP methods are used?

### Step 3: Find the Culprit
Compare evidence:
- Which upstream service has errors?
- Do the error types match? (e.g., victim gets 404, upstream returns 404)
- Which service's errors started FIRST?
- Are there recent commits in the culprit service?

### Step 4: Correlate Timeline
Check timestamps:
- When was the last commit deployed?
- When did errors start?
- Do they correlate? (commit at 01:57, errors at 01:58 = likely cause)

---

## ERROR PATTERN GUIDE

**405 Method Not Allowed:**
- Indicates HTTP method mismatch (GET vs POST, etc.)
- Check: What method does caller use? What does upstream expect?
- Root cause: Usually a recent change in caller's request method OR upstream's accepted methods

**404 Not Found:**
- Indicates missing endpoint or wrong URL
- Check: Is caller using correct endpoint? Did upstream remove/rename the endpoint?
- Root cause: URL mismatch, routing config change, or service unavailable

**401/403 Authentication:**
- Indicates auth failure
- Check: Token validation, auth service logs, authentication flow
- Root cause: Auth service change, token format change, or expired credentials

**500 Internal Server Error:**
- Indicates code bug or exception in upstream
- Check: Stack traces, recent code changes, exception logs
- Root cause: Code bug, unhandled exception, configuration error

**Timeouts/503:**
- Indicates performance issue or service unavailability
- Check: Metrics (CPU, memory, latency), resource exhaustion
- Root cause: Performance degradation, resource limits, overload

---

## OUTPUT FORMAT

You MUST respond in this exact format:

ROOT_SERVICE: <service_name>
ROOT_CAUSE: <one clear, specific sentence>
ROOT_COMMIT: <commit_id or "none">
CONFIDENCE: <0-100>
REASONING: <2-3 sentences explaining your analysis>

### Field Requirements:

**ROOT_SERVICE:**
- The service where the ACTUAL problem originated (usually NOT the service user reported)
- Use exact service name from logs/code (lowercase, no "-service" suffix)
- If truly unknown after analysis, use "unknown" (but try hard to identify)

**ROOT_CAUSE:**
- ONE clear, actionable sentence explaining exactly what went wrong
- MUST include specifics: What changed? Where? Why did it break?
- Good: "api-service line 123 changed HTTP method from POST to GET for /verify endpoint"
- Bad: "api has a bug" (too vague)
- Include file path, line number, commit ID if known
- Be precise about the mechanism of failure

**ROOT_COMMIT:**
- Commit hash that introduced the problem (e.g., "da3c6383")
- Only if: (a) commit identified AND (b) timestamp correlates with error start
- Use "none" if no commit identified or no correlation

**CONFIDENCE:**
- 90-100: All evidence aligns perfectly, clear root cause, known commit
- 70-89: Strong evidence, clear root cause, minor gaps
- 50-69: Some evidence, likely root cause, significant gaps
- 0-49: Insufficient evidence, multiple possibilities
- Be honest about gaps in evidence

**REASONING:**
- 2-3 sentences max
- Explain: What evidence led to this conclusion?
- Explain: Why is this service the culprit (not just a victim)?
- Explain: How does the failure mechanism work?
- Mention timeline correlation if applicable

---

## EXAMPLES:

### Example 1: Method Mismatch (405)
Evidence:
- frontend logs: 404 errors at 01:58:05 calling api-service
- api logs: 405 errors at 01:58:00 calling auth
- api code: Uses GET for auth/verify
- auth code: Only accepts POST for /verify
- api commit abc1234 at 01:57: "improvement: changed request method"

Analysis:
- Victim: frontend (reported by user)
- Culprit: api (405 errors started 5 seconds earlier)
- Mechanism: api calls auth with GET, auth only accepts POST
- Root cause: api commit changed POST → GET

Output:
ROOT_SERVICE: api
ROOT_CAUSE: Commit abc1234 in api-service changed line 123 from POST to GET when calling auth-service /verify endpoint, causing 405 Method Not Allowed errors that cascaded to frontend as 404 errors
ROOT_COMMIT: abc1234
CONFIDENCE: 95
REASONING: API errors started 5 seconds before frontend, indicating api is upstream culprit. Code analysis confirms method mismatch (GET vs POST). Commit timestamp (01:57) directly precedes error start (01:58), establishing clear causation.

### Example 2: Performance Degradation
Evidence:
- frontend logs: Timeout errors starting 02:15
- api logs: Slow responses (5-10s latency) starting 02:14
- api metrics: CPU 95%, memory 90%
- No recent commits in either service

Analysis:
- Victim: frontend (timeouts due to slow upstream)
- Culprit: api (performance degradation started first)
- Mechanism: api overload → slow responses → frontend timeouts
- Root cause: Resource exhaustion in api (no code change)

Output:
ROOT_SERVICE: api
ROOT_CAUSE: api-service experiencing resource exhaustion (95% CPU, 90% memory) causing 5-10 second response times that triggered cascading timeouts in frontend-service
ROOT_COMMIT: none
CONFIDENCE: 80
REASONING: API performance degradation (02:14) occurred 1 minute before frontend timeouts (02:15), confirming upstream causation. Metrics clearly show resource exhaustion. However, no recent commits identified, suggesting operational issue rather than code change.

---

## CRITICAL REMINDERS:

1. **TRACE UPSTREAM**: Don't stop at the reported service. Follow the dependency chain.
2. **TIMELINE IS KEY**: The service with EARLIEST errors is usually the culprit.
3. **ERROR CODES TELL A STORY**: 405 = method mismatch, 404 = missing endpoint, etc.
4. **CODE REVEALS DEPENDENCIES**: Read code to understand what calls what.
5. **COMMITS NEAR ERROR START**: Commits deployed 0-2 hours before errors are highly suspect.
6. **BE SPECIFIC**: "Line 123 changed POST to GET" beats "service has a bug".

---

## NOW ANALYZE THE EVIDENCE:

Follow the systematic analysis framework above. Think through each step. Identify the victim, trace upstream, find the culprit, and explain the root cause with specific details.

Your analysis:
"""
        
        # Add timeout to LLM call (analysis can be longer)
        files = state.get("files", [])
        messages = prepare_multimodal_messages(context, files)
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=60.0
        )
        content = response.content.strip()
        
        logger.info(f"Analysis response: {content}")
        
        # Parse response
        root_service = extract_field(content, "ROOT_SERVICE")
        root_cause = extract_field(content, "ROOT_CAUSE")
        root_commit = extract_field(content, "ROOT_COMMIT")
        confidence_str = extract_field(content, "CONFIDENCE")
        
        # Parse confidence
        try:
            confidence = float(confidence_str) / 100.0  # Convert to 0-1
        except:
            confidence = 0.7  # Default
        
        logger.info(f"Root cause: {root_cause} (confidence: {confidence})")
        
        # Add to intermediate steps
        intermediate_steps = state.get("intermediate_steps", [])
        intermediate_steps.append({
            "step": "analyze_trace",
            "result": {
                "root_service": root_service,
                "root_cause": root_cause,
                "confidence": confidence
            }
        })
        
        return {
            "root_service": root_service,
            "root_cause": root_cause,
            "root_commit": root_commit if root_commit != "none" else None,
            "confidence": confidence,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in analyze_and_trace_node: {e}")
        return {
            "root_service": "unknown",
            "root_cause": f"Error during analysis: {str(e)}",
            "root_commit": None,
            "confidence": 0.0,
            "error": str(e),
        }


# ============================================================================
# Node 5: GENERATE
# ============================================================================

async def generate_report_node(
    state: RCAStateV2,
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Generate final report in Slack format.
    
    Supports two modes:
    1. NEW (multi-level RCA): Uses investigation_chain to show full dependency chain
    2. OLD (single-level): Uses traditional root cause report
    
    Input: All investigation results
    Output: final_report
    """
    logger.info("NODE: generate_report_node")
    
    try:
        user_query = state.get("user_query")
        primary_service = state.get("primary_service")
        root_service = state.get("root_service")
        root_cause = state.get("root_cause")
        root_commit = state.get("root_commit")
        logs_summary = state.get("logs_summary", {})
        commit_findings = state.get("commit_findings", {})
        confidence = state.get("confidence", 0.7)
        
        # NEW: Check for multi-level RCA data
        investigation_chain = state.get("investigation_chain", [])
        victim_service = state.get("victim_service", primary_service)
        intermediate_services = state.get("intermediate_services", [])
        
        # Extract telemetry from intermediate_steps
        intermediate_steps = state.get("intermediate_steps", [])
        telemetry_info = ""
        for step in intermediate_steps:
            if step.get("step") == "investigate" and "telemetry" in step:
                telemetry = step["telemetry"]
                skipped = telemetry.get("skipped_tools", [])
                if skipped:
                    reasons = []
                    for skip in skipped:
                        tool = skip.get("tool")
                        reason = skip.get("reason", "").replace("_", " ")
                        reasons.append(f"{tool} ({reason})")
                    telemetry_info = f"\n\n**Note:** Some investigation tools were not available: {', '.join(reasons)}. Consider integrating New Relic, Grafana, or Datadog for more comprehensive analysis."
                break
        
        # Query type already determined by router node
        query_type = state.get("query_type", "incident")
        is_incident = query_type == "incident"
        
        if not is_incident:
            # For casual queries, generate simple response
            prompt = GENERATE_CASUAL_PROMPT_V1.format(user_query=user_query)
        elif investigation_chain and len(investigation_chain) > 1:
            # NEW: Multi-level RCA report (shows full dependency chain)
            logger.info("📋 Generating multi-level RCA report")
            
            # Build investigation chain summary
            chain_summary = ""
            for i, item in enumerate(investigation_chain):
                service = item["service"]
                findings = item["findings"]
                depth = item["depth"]
                decision = item.get("decision", {})
                
                chain_summary += f"\n**Level {depth + 1}: `{service}`**\n"
                chain_summary += f"- Decision: {decision.get('decision', 'N/A')}\n"
                chain_summary += f"- Reasoning: {decision.get('reasoning', 'N/A')}\n"
                
                # Add key findings
                if findings.get("logs_summary", {}).get(service):
                    logs = findings["logs_summary"][service]
                    chain_summary += f"- Logs: {str(logs)[:150]}...\n"
                if findings.get("metrics_summary", {}).get(service):
                    metrics = findings["metrics_summary"][service]
                    chain_summary += f"- Metrics: {str(metrics)[:150]}...\n"
                if findings.get("commit_findings", {}).get(service):
                    commits = findings["commit_findings"][service]
                    chain_summary += f"- Recent commits: {str(commits)[:150]}...\n"
                chain_summary += "\n"
            
            # Format intermediate services
            intermediate_str = ", ".join([f"`{s}`" for s in intermediate_services]) if intermediate_services else "None"
            
            prompt = MULTI_LEVEL_RCA_REPORT_PROMPT_V1.format(
                investigation_chain=chain_summary,
                victim_service=victim_service or primary_service,
                intermediate_services=intermediate_str,
                root_service=root_service,
                root_cause=root_cause,
                root_commit=root_commit or "none",
                confidence=int(confidence * 100)
            )
        else:
            # OLD: Single-level RCA report (backward compatibility)
            logger.info("📋 Generating single-level RCA report")
            prompt = GENERATE_INCIDENT_PROMPT_V1.format(
                user_query=user_query,
                primary_service=primary_service,
                root_service=root_service,
                root_cause=root_cause,
                root_commit=(root_commit or "Not identified"),
                evidence_summary=format_dict_for_context(logs_summary, max_length=1000),
                recent_commits=format_dict_for_context(commit_findings, max_length=1000),
            )
        
        # Add timeout to LLM call (report generation can be longer)
        files = state.get("files", [])
        messages = prepare_multimodal_messages(prompt, files)
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=60.0
        )
        final_report = response.content.strip()
        
        # Append telemetry info if tools were skipped
        if telemetry_info:
            final_report += telemetry_info
        
        logger.info(f"Generated report: {len(final_report)} chars")
        
        # Add to intermediate steps
        intermediate_steps = state.get("intermediate_steps", [])
        intermediate_steps.append({
            "step": "generate",
            "result": "Report generated",
            "report_length": len(final_report),
            "telemetry_appended": bool(telemetry_info),
        })
        
        return {
            "final_report": final_report,
            "intermediate_steps": intermediate_steps,
        }
        
    except Exception as e:
        logger.error(f"Error in generate_report_node: {e}")
        
        # Fallback report
        fallback_report = f"""✅ Investigation complete


*What's going on*

{state.get('user_query', 'Investigating incident')}

*Root cause*

{state.get('root_cause', 'Unable to determine root cause')}

*Next steps*

• Review logs and metrics manually
• Check recent deployments
• Contact on-call engineer

*Prevention*

• Add monitoring for this scenario
• Improve alerting thresholds
"""
        
        return {
            "final_report": fallback_report,
            "error": str(e),
        }
