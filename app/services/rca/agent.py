"""
RCA Agent Service using LangChain with Groq LLM
"""
import logging
from typing import Dict, Any, Optional
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from .prompts import RCA_SYSTEM_PROMPT
from .tools import (
    fetch_logs_tool,
    fetch_error_logs_tool,
    fetch_cpu_metrics_tool,
    fetch_memory_metrics_tool,
    fetch_http_latency_tool,
    fetch_metrics_tool,
)

logger = logging.getLogger(__name__)


class RCAAgentService:
    """
    Service for Root Cause Analysis using AI agent with ReAct pattern
    """

    def __init__(self):
        """Initialize the RCA agent with Groq LLM and observability tools"""
        self.llm = None
        self.agent_executor = None
        self._initialize_agent()

    def _initialize_agent(self):
        """Initialize the LangChain agent with tools"""
        try:
            # Initialize Groq LLM
            if not settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not configured in environment")

            self.llm = ChatGroq(
                api_key=settings.GROQ_API_KEY,
                model="llama-3.3-70b-versatile",  # Groq's best model for reasoning
                temperature=0.1,  # Low temperature for consistent, focused analysis
                max_tokens=4096,
            )

            # Define available tools for the agent
            tools = [
                fetch_error_logs_tool,  # High priority - start here
                fetch_logs_tool,
                fetch_cpu_metrics_tool,
                fetch_memory_metrics_tool,
                fetch_http_latency_tool,
                fetch_metrics_tool,
            ]

            # Create chat prompt template with system message
            # This uses the newer ChatPromptTemplate format for better tool calling
            prompt = ChatPromptTemplate.from_messages([
                ("system", RCA_SYSTEM_PROMPT),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            # Create the tool-calling agent (newer, more reliable than create_react_agent)
            agent = create_tool_calling_agent(
                llm=self.llm,
                tools=tools,
                prompt=prompt,
            )

            # Create agent executor with configuration
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                verbose=True,  # Enable verbose logging for debugging
                max_iterations=15,  # Allow up to 15 tool calls
                max_execution_time=180,  # 3 minute timeout
                handle_parsing_errors=True,  # Gracefully handle LLM parsing errors
                return_intermediate_steps=True,  # Return reasoning steps
            )

            logger.info("RCA Agent initialized successfully with Groq LLM and tool calling")

        except Exception as e:
            logger.error(f"Failed to initialize RCA agent: {e}")
            raise

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform root cause analysis for the given user query

        Args:
            user_query: User's question or issue description (e.g., "Why is my xyz service slow?")
            context: Optional context from Slack (user_id, channel_id, etc.)

        Returns:
            Dictionary containing:
                - output: The RCA analysis text
                - intermediate_steps: List of reasoning steps taken
                - success: Whether analysis completed successfully
                - error: Error message if failed
        """
        try:
            logger.info(f"Starting RCA analysis for query: '{user_query}'")

            # Prepare input for the agent
            agent_input = {
                "input": user_query,
            }

            # Execute the agent asynchronously
            result = await self.agent_executor.ainvoke(agent_input)

            logger.info("RCA analysis completed successfully")

            return {
                "output": result.get("output", "Analysis completed but no output generated."),
                "intermediate_steps": result.get("intermediate_steps", []),
                "success": True,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Error during RCA analysis: {e}", exc_info=True)
            return {
                "output": None,
                "intermediate_steps": [],
                "success": False,
                "error": f"RCA analysis failed: {str(e)}",
            }

    async def analyze_with_retry(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Perform RCA analysis with automatic retry on failure

        Args:
            user_query: User's question
            context: Optional context
            max_retries: Maximum number of retry attempts

        Returns:
            Analysis result dictionary
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self.analyze(user_query, context)

                if result["success"]:
                    return result

                # If analysis didn't succeed but didn't error, retry
                logger.warning(f"Analysis attempt {attempt + 1} did not succeed, retrying...")

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")

                if attempt == max_retries:
                    return {
                        "output": None,
                        "intermediate_steps": [],
                        "success": False,
                        "error": f"RCA failed after {max_retries + 1} attempts: {str(e)}",
                    }

        # Should not reach here, but handle edge case
        return {
            "output": None,
            "intermediate_steps": [],
            "success": False,
            "error": "RCA analysis failed for unknown reasons",
        }

    def get_agent_info(self) -> Dict[str, Any]:
        """
        Get information about the configured agent

        Returns:
            Dictionary with agent configuration details
        """
        return {
            "model": "llama-3.3-70b-versatile",
            "provider": "Groq",
            "max_iterations": 10,
            "max_execution_time": 120,
            "available_tools": [
                "fetch_error_logs_tool",
                "fetch_logs_tool",
                "fetch_cpu_metrics_tool",
                "fetch_memory_metrics_tool",
                "fetch_http_latency_tool",
                "fetch_metrics_tool",
            ],
        }


# Singleton instance
rca_agent_service = RCAAgentService()
