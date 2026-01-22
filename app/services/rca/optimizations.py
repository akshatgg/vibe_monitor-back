"""
Context optimization utilities for RCA Agent V2.
Reduces token usage through summarization, filtering, and chunking.
"""

import logging
from typing import Dict, Any, Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


# ============================================================================
# Log Summarization
# ============================================================================

async def summarize_logs(logs: str, llm: BaseChatModel, max_input_chars: Optional[int] = None) -> str:
    """
    Summarize log entries to reduce context length.
    
    Converts:
        10K lines, 50K tokens → "87x 405 errors from /verify, started 01:58"
    
    Args:
        logs: Raw log text
        llm: Language model for summarization
        max_input_chars: Max chars to send to LLM (None = no limit, analyze full logs)
    
    Returns:
        Concise summary (2-3 sentences, ~50-200 tokens)
    """
    try:
        if not logs or len(logs.strip()) == 0:
            return "No log entries found."
        
        # No truncation - analyze full logs
        logs_to_summarize = logs
        
        prompt = f"""You are summarizing log entries for a Root Cause Analysis investigation. Extract only the CRITICAL information.

## LOG ENTRIES:
{logs_to_summarize}

## YOUR TASK:
Create a concise summary (2-3 sentences MAX) that captures:
1. **Error patterns**: What errors are occurring? (error codes, error messages, exception types)
2. **Frequency**: How many times? (e.g., "87 occurrences", "every request", "sporadic")
3. **Timeline**: When did it start? (specific timestamp if available)
4. **Affected components**: Which endpoints, services, or functions are failing?
5. **Key indicators**: Any upstream dependency failures mentioned? (e.g., "Failed to call X", "Connection refused to Y")

## SUMMARY GUIDELINES:
- Focus ONLY on errors, failures, exceptions, and critical issues
- Ignore INFO logs, debug messages, successful operations
- Extract specific error codes (404, 405, 500, etc.)
- Extract specific error messages
- Include timestamps if they show when errors started
- Mention service/endpoint names if they're part of the error
- Be specific: "87x 405 Method Not Allowed errors from /verify endpoint" not "some errors"

## OUTPUT FORMAT:
Write 2-3 sentences that a human SRE can quickly understand:
- Sentence 1: What errors are happening and how often
- Sentence 2: When they started and which endpoints/services are affected
- Sentence 3: Any upstream dependency indicators or critical patterns

## EXAMPLES:

Example 1:
Logs: [1000 lines of logs with 87 instances of "405 Method Not Allowed" from /verify endpoint starting at 01:58:00]
Summary: "87 occurrences of 405 Method Not Allowed errors from /verify endpoint, starting at 01:58:00 UTC. All errors originated from service-a calling upstream service with incorrect HTTP method."

Example 2:
Logs: [500 lines showing sporadic 500 errors, connection timeouts]
Summary: "Sporadic 500 Internal Server errors and connection timeouts detected. Errors appear randomly across multiple endpoints, suggesting potential resource exhaustion or upstream service issues."

Example 3:
Logs: [200 lines, all successful operations]
Summary: "No errors found in logs. All operations completed successfully during the time period."

## NOW SUMMARIZE THE LOGS ABOVE:

Summary:"""
        
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        summary = response.content.strip()
        
        logger.info(f"Summarized logs: {len(logs)} chars → {len(summary)} chars")
        return summary
        
    except Exception as e:
        logger.error(f"Error summarizing logs: {e}")
        # Fallback: return first 500 chars
        return logs[:500] + "..." if len(logs) > 500 else logs


# ============================================================================
# Metrics Summarization
# ============================================================================

def summarize_metrics(metrics: Dict[str, Any]) -> str:
    """
    Summarize metrics to key insights.
    
    Converts:
        Complex dict with many data points → "Error rate: 15.2%, Latency p99: 450ms"
    
    Args:
        metrics: Metrics dictionary
    
    Returns:
        Concise text summary
    """
    try:
        if not metrics:
            return "No metrics data available."
        
        parts = []
        
        # Common metric keys
        if "error_rate" in metrics:
            parts.append(f"Error rate: {metrics['error_rate']}%")
        if "latency_p99" in metrics:
            parts.append(f"Latency p99: {metrics['latency_p99']}ms")
        if "throughput" in metrics:
            parts.append(f"Throughput: {metrics['throughput']} req/s")
        if "cpu_percent" in metrics:
            parts.append(f"CPU: {metrics['cpu_percent']}%")
        if "memory_percent" in metrics:
            parts.append(f"Memory: {metrics['memory_percent']}%")
        
        # If no known keys, just convert to string
        if not parts:
            parts.append(str(metrics)[:200])
        
        return ", ".join(parts)
        
    except Exception as e:
        logger.error(f"Error summarizing metrics: {e}")
        return str(metrics)[:200]


# ============================================================================
# Code Summarization
# ============================================================================

async def extract_key_info_from_code(
    code: str,
    llm: BaseChatModel,
    max_input_chars: Optional[int] = None  # No limit - analyze full file
) -> str:
    """
    Extract key information from code file.
    
    Converts:
        500 lines of code → "Main service handler, calls /verify endpoint with GET request"
    
    Args:
        code: Source code text
        llm: Language model
        max_input_chars: Max chars to send to LLM (None = no limit, analyze full file)
    
    Returns:
        Code summary (2-3 sentences)
    """
    try:
        if not code or len(code.strip()) == 0:
            return "No code content found."
        
        # No truncation - analyze the full file
        code_to_analyze = code
        
        prompt = f"""You are analyzing code for a Root Cause Analysis investigation. Extract key information about what this code does and its dependencies.

## CODE TO ANALYZE:
{code_to_analyze}

## YOUR TASK:
**CRITICAL**: First, scan the code for sleep/delay statements. If you find ANY, that's the MOST IMPORTANT finding.

Create a concise summary (2-4 sentences) that captures:
1. **PERFORMANCE ISSUES FIRST**: If you find sleep(), time.sleep(), setTimeout(), delay(), wait(), or ANY blocking call, START your summary with "PERFORMANCE ISSUE: [exact code found]" (e.g., "PERFORMANCE ISSUE: time.sleep(5) found")
2. **Main purpose**: What is this code's primary function? (e.g., "API endpoint handler", "service client", "authentication middleware")
3. **Service dependencies**: What OTHER services does this code depend on? Extract ALL service names/endpoints it calls (look for HTTP requests, API calls, service URLs, function calls to other services)
4. **External dependencies**: What external APIs, databases, or resources does it use? (database calls, third-party APIs, message queues)

## ANALYSIS GUIDELINES:
- **CRITICAL**: Extract ALL service dependencies (HTTP requests, API calls, gRPC calls, message queue consumers/producers)
- Identify HTTP methods used (GET, POST, PUT, DELETE) and endpoints
- Look for service URLs in environment variables or configuration (e.g., AUTH_SERVICE_URL, MARKETPLACE_API)
- Check for import statements that reference other services
- Identify database connections and queries
- **CRITICAL - PERFORMANCE ISSUES**: You MUST identify and explicitly mention:
  * sleep(), time.sleep(), Thread.sleep(), setTimeout(), delay(), wait(), asyncio.sleep()
  * ANY artificial delays, hardcoded waits, or blocking calls
  * Retry loops with delays
  * Long-running loops or blocking operations
  * If you find ANY sleep/delay/wait statement, you MUST include it in the summary with the exact duration (e.g., "time.sleep(5)" or "sleep(3 seconds)")
- Note authentication/authorization calls
- Identify timeout configurations
- Note any hardcoded delays or rate limiting that could cause latency

## OUTPUT FORMAT:
Write 2-4 sentences (use more if you find performance issues):
- Sentence 1: Main purpose and which OTHER SERVICES it depends on (extract all service names)
- Sentence 2: External dependencies (databases, APIs, message queues) and how it calls them
- Sentence 3: **MANDATORY if sleep/delay found**: Explicitly state "PERFORMANCE ISSUE: [exact sleep/delay statement found]" with the exact code (e.g., "PERFORMANCE ISSUE: time.sleep(5) found on line X" or "PERFORMANCE ISSUE: setTimeout(3000) found")
- Sentence 4: Other performance concerns (timeouts, loops) and potential issues

## EXAMPLES:

Example 1:
Code: [Python code showing requests.get() call to auth service + time.sleep(2)]
Summary: "API handler that depends on 'auth' service for token verification via GET /verify endpoint. Has artificial 2-second delay (time.sleep(2)) before each request. Performance issue: hardcoded delay causes latency."

Example 2:
Code: [Go code calling payment-service and user-service with retry logic]
Summary: "Transaction processor that depends on 'payment' service (/charge endpoint) and 'user' service (/profile endpoint). Uses PostgreSQL database with 5-second query timeout. Retry logic with exponential backoff could amplify latency."

Example 3:
Code: [JavaScript with setTimeout and multiple service dependencies]
Summary: "Frontend orchestrator that depends on 'backend-api' (/products), 'analytics' (/track), and 'recommendations' (/suggest) services. Uses setTimeout with 3-second delays between calls. Sequential calling pattern causes cumulative latency."

## NOW ANALYZE THE CODE ABOVE:

Summary:"""
        
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        summary = response.content.strip()
        
        logger.info(f"Summarized code: {len(code)} chars → {len(summary)} chars")
        return summary
        
    except Exception as e:
        logger.error(f"Error summarizing code: {e}")
        return code[:300] + "..." if len(code) > 300 else code


# ============================================================================
# Commit Summarization
# ============================================================================

def summarize_commits(commits: Any) -> str:
    """
    Summarize commit history to key changes.
    
    Args:
        commits: Commit data (could be list or formatted string)
    
    Returns:
        Summary of recent commits
    """
    try:
        if isinstance(commits, str):
            # Already formatted, just truncate if too long
            return commits[:1000] + "..." if len(commits) > 1000 else commits
        
        # If it's a list or dict, convert to string
        return str(commits)[:1000]
        
    except Exception as e:
        logger.error(f"Error summarizing commits: {e}")
        return str(commits)[:500]


# ============================================================================
# Relevance Filtering
# ============================================================================

def filter_error_logs(logs: str, error_keywords: Optional[list] = None) -> str:
    """
    Filter logs to keep only error-related entries.
    
    Reduces context by 70-90% by dropping INFO/DEBUG logs.
    
    Args:
        logs: Raw log text
        error_keywords: Keywords to filter for (default: ["error", "fail", "exception"])
    
    Returns:
        Filtered logs with only errors
    """
    try:
        if not error_keywords:
            error_keywords = [
                "error", "err", "fail", "failed", "failure",
                "exception", "fatal", "critical", "warning",
                "timeout", "refused", "denied", "invalid",
                "404", "500", "502", "503", "405"
            ]
        
        lines = logs.split("\n")
        error_lines = []
        
        for line in lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in error_keywords):
                error_lines.append(line)
        
        if not error_lines:
            # No errors found, return first 10 lines
            return "\n".join(lines[:10]) + "\n... (no errors found in logs)"
        
        filtered = "\n".join(error_lines)
        logger.info(f"Filtered logs: {len(lines)} lines → {len(error_lines)} error lines")
        return filtered
        
    except Exception as e:
        logger.error(f"Error filtering logs: {e}")
        return logs


# ============================================================================
# Helper: Format Dict for Context
# ============================================================================

def format_dict_for_context(data: Dict[str, Any], max_length: int = 2000) -> str:
    """
    Format dictionary as readable text for context.
    
    Args:
        data: Dictionary to format
        max_length: Max length of output
    
    Returns:
        Formatted text
    """
    try:
        if not data:
            return "(empty)"
        
        lines = []
        for key, value in data.items():
            # Truncate value if too long
            value_str = str(value)
            if len(value_str) > 500:
                value_str = value_str[:500] + "..."
            
            lines.append(f"{key}: {value_str}")
        
        result = "\n".join(lines)
        
        # Truncate if total is too long
        if len(result) > max_length:
            result = result[:max_length] + "\n... (truncated)"
        
        return result
        
    except Exception as e:
        logger.error(f"Error formatting dict: {e}")
        return str(data)[:max_length]


# ============================================================================
# Helper: Extract Field from LLM Response
# ============================================================================

def extract_field(text: str, field_name: str) -> str:
    """
    Extract a field from LLM response text.
    
    Example:
        text = "PRIMARY_SERVICE: service-a\\nSYMPTOMS: errors, slowness"
        extract_field(text, "PRIMARY_SERVICE") → "service-a"
    
    Args:
        text: Response text
        field_name: Field to extract
    
    Returns:
        Extracted value or "unknown"
    """
    try:
        lines = text.split("\n")
        for line in lines:
            if field_name in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip()
        
        return "unknown"
        
    except Exception as e:
        logger.error(f"Error extracting field '{field_name}': {e}")
        return "unknown"
