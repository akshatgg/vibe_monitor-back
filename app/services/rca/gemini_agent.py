"""
RCA Agent Service using LangChain with Gemini LLM (supports multimodal inputs: text + images)
"""

import base64
import logging
import re
import io
import httpx
from functools import partial
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from pydantic import BaseModel, create_model
from PIL import Image
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from .prompts import RCA_SYSTEM_PROMPT
from .tools.grafana.tools import (
    fetch_logs_tool,
    fetch_error_logs_tool,
    fetch_cpu_metrics_tool,
    fetch_memory_metrics_tool,
    fetch_http_latency_tool,
    fetch_metrics_tool,
    get_datasources_tool,
    get_labels_tool,
    get_label_values_tool,
)

from .tools.github.tools import (
    get_repository_commits_tool,
    list_pull_requests_tool,
    search_code_tool,
    download_file_tool,
    read_repository_file_tool,
    get_repository_tree_tool,
    get_branch_recent_commits_tool,
    get_repository_metadata_tool,
)

logger = logging.getLogger(__name__)

# Define all available RCA tools in one place (single source of truth)
ALL_RCA_TOOLS = [
    # Grafana/Observability tools
    fetch_error_logs_tool,
    fetch_logs_tool,
    fetch_cpu_metrics_tool,
    fetch_memory_metrics_tool,
    fetch_http_latency_tool,
    fetch_metrics_tool,
    get_datasources_tool,
    get_labels_tool,
    get_label_values_tool,
    # GitHub tools
    read_repository_file_tool,
    search_code_tool,
    get_repository_commits_tool,
    list_pull_requests_tool,
    download_file_tool,
    get_repository_tree_tool,
    get_branch_recent_commits_tool,
    get_repository_metadata_tool,
]


class GeminiRCAAgentService:
    """
    Service for Root Cause Analysis using AI agent with Gemini (supports images)
    """

    def __init__(self):
        """Initialize the RCA agent with Gemini LLM (shared across all requests)"""
        self.llm = None
        self.prompt = None
        self._initialize_llm()

    def _initialize_llm(self):
        """Initialize the shared LLM and prompt template"""
        try:
            # Initialize Gemini LLM (stateless, can be shared)
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not configured in environment")

            self.llm = ChatGoogleGenerativeAI(
                model=settings.GEMINI_LLM_MODEL,
                google_api_key=settings.GEMINI_API_KEY,
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_output_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )
            logger.info(f"Using {settings.GEMINI_LLM_MODEL} for image analysis")

            # Create chat prompt template with system message, service mapping, and thread history
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", RCA_SYSTEM_PROMPT + "\n\n## 📋 SERVICE→REPOSITORY MAPPING\n\n{service_mapping_text}\n\n{thread_history_text}"),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            logger.info("Gemini RCA Agent LLM initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Gemini RCA agent LLM: {e}")
            raise

    def _create_schema_without_workspace_id(
        self, original_schema: type[BaseModel]
    ) -> type[BaseModel]:
        """
        Create a new Pydantic schema excluding the workspace_id field.

        Args:
            original_schema: The original tool schema that includes workspace_id

        Returns:
            A new schema with workspace_id field removed
        """
        # Get all fields except workspace_id
        fields = {
            name: (field.annotation, field)
            for name, field in original_schema.model_fields.items()
            if name != "workspace_id"
        }

        # Create new model without workspace_id
        new_schema = create_model(
            f"{original_schema.__name__}WithoutWorkspace", **fields
        )

        return new_schema

    def _create_agent_executor_for_workspace(self, workspace_id: str) -> AgentExecutor:
        """
        Create a workspace-specific agent executor with tools bound to the given workspace_id.

        This method creates a new executor for each request to ensure thread-safety and
        prevent workspace_id conflicts between concurrent requests.

        Args:
            workspace_id: The workspace ID to bind to all tools

        Returns:
            AgentExecutor configured for the specific workspace
        """
        # Dynamically bind workspace_id to all tools with modified schemas
        tools_with_workspace = []

        for tool in ALL_RCA_TOOLS:
            # Create schema without workspace_id (since it's pre-bound)
            modified_schema = self._create_schema_without_workspace_id(tool.args_schema)

            # Create wrapped tool with partial application and modified schema
            wrapped_tool = StructuredTool.from_function(
                coroutine=partial(tool.coroutine, workspace_id=workspace_id),
                name=tool.name,
                description=tool.description,
                args_schema=modified_schema,
            )

            tools_with_workspace.append(wrapped_tool)

        # Create the tool-calling agent with workspace-specific tools
        agent = create_tool_calling_agent(
            llm=self.llm,
            tools=tools_with_workspace,
            prompt=self.prompt,
        )

        # Create and return executor for this workspace
        executor = AgentExecutor(
            agent=agent,
            tools=tools_with_workspace,
            verbose=True,
            max_iterations=settings.RCA_AGENT_MAX_ITERATIONS,
            max_execution_time=settings.RCA_AGENT_MAX_EXECUTION_TIME,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )

        logger.info(f"Created Gemini agent executor for workspace: {workspace_id}")
        return executor

    async def _download_slack_images(
        self, files: List[Dict[str, Any]], access_token: str
    ) -> List[Dict[str, Any]]:
        """
        Download images from Slack URLs.

        Args:
            files: List of file objects from Slack event
            access_token: Slack bot access token for authentication

        Returns:
            List of downloaded image data with metadata
        """
        downloaded_images = []

        async with httpx.AsyncClient() as client:
            for file_obj in files:
                # Only process images
                mimetype = file_obj.get("mimetype", "")
                if not mimetype.startswith("image/"):
                    logger.info(f"Skipping non-image file: {file_obj.get('name')} ({mimetype})")
                    continue

                # Use url_private_download for direct download
                url_download = file_obj.get("url_private_download") or file_obj.get("url_private")
                if not url_download:
                    logger.warning(f"No download URL for file: {file_obj.get('name')}")
                    continue

                try:
                    # Download image with Slack auth
                    # IMPORTANT: Don't auto-follow redirects - httpx drops auth headers on cross-domain redirects
                    # We need to manually follow redirects while preserving the Authorization header
                    max_redirects = settings.RCA_SLACK_IMAGE_MAX_REDIRECTS
                    current_url = url_download

                    for redirect_count in range(max_redirects):
                        response = await client.get(
                            current_url,
                            headers={"Authorization": f"Bearer {access_token}"},
                            timeout=settings.RCA_SLACK_IMAGE_DOWNLOAD_TIMEOUT,
                            follow_redirects=False,  # Manual redirect handling to preserve auth
                        )

                        # If not a redirect, we got the final response
                        if response.status_code not in (301, 302, 303, 307, 308):
                            response.raise_for_status()
                            break

                        # Get redirect location and follow it with auth header
                        redirect_url = response.headers.get("location")
                        if not redirect_url:
                            raise Exception("Redirect response missing Location header")

                        # Parse redirect URL to validate domain
                        parsed = urlparse(redirect_url)

                        # only follow redirects to files.slack.com, not the slack login or workspace url, we need an image hrere.
                        if parsed.netloc and not parsed.netloc.startswith("files.slack.com"):
                            logger.error(
                                f"Rejecting redirect to non-files domain: {parsed.netloc}. "
                                f"This typically indicates an authentication issue. "
                                f"Slack workspace URLs return HTML login pages, not images."
                            )
                            raise Exception(
                                f"Invalid redirect to {parsed.netloc} - expected files.slack.com. "
                                f"This may indicate an expired or invalid access token."
                            )

                        current_url = redirect_url

                        # Sanitize URL to prevent token exposure in logs
                        safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        logger.info(f"Following redirect ({redirect_count + 1}/{max_redirects}): {safe_url}")
                    else:
                        raise Exception(f"Too many redirects (>{max_redirects}) while downloading {file_obj.get('name')}")

                    # Debug: Check what we actually downloaded
                    content_type = response.headers.get("content-type", "unknown")
                    first_bytes = response.content[:100] if len(response.content) >= 100 else response.content

                    # Validate we got an image, not HTML
                    if content_type.startswith("text/html"):
                        logger.error(
                            f"Received HTML instead of image for {file_obj.get('name')}. "
                            f"Content-Type: {content_type}, First bytes: {first_bytes[:50]!r}"
                        )
                        raise Exception(
                            f"Failed to download {file_obj.get('name')}: received HTML page instead of image. "
                            f"This may indicate an authentication issue or invalid URL."
                        )

                    logger.info(
                        f"Downloaded {file_obj.get('name')}: "
                        f"{len(response.content)} bytes, "
                        f"Content-Type: {content_type}, "
                        f"First bytes: {first_bytes[:50]!r}"
                    )

                    downloaded_images.append({
                        "name": file_obj.get("name", "image"),
                        "mimetype": mimetype,
                        "data": response.content,
                        "size": len(response.content),
                    })

                    logger.info(f"Downloaded image: {file_obj.get('name')} ({len(response.content)} bytes)")

                except Exception as e:
                    logger.error(f"Failed to download image {file_obj.get('name')}: {e}")

        return downloaded_images

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Perform root cause analysis for the given user query (supports images)

        Args:
            user_query: User's question or issue description (e.g., "Why is my xyz service slow?")
            context: Optional context from Slack (user_id, channel_id, workspace_id, files, etc.)
            callbacks: Optional list of callback handlers (e.g., for Slack progress updates)

        Returns:
            Dictionary containing:
                - output: The RCA analysis text
                - intermediate_steps: List of reasoning steps taken
                - success: Whether analysis completed successfully
                - error: Error message if failed
        """
        try:
            # Extract workspace_id from context (REQUIRED - no default)
            workspace_id = (context or {}).get("workspace_id")

            if not workspace_id:
                error_msg = "workspace_id is required in context for RCA analysis"
                logger.error(error_msg)
                return {
                    "output": None,
                    "intermediate_steps": [],
                    "success": False,
                    "error": error_msg,
                }

            logger.info(
                f"Starting Gemini RCA analysis for query: '{user_query}' (workspace: {workspace_id})"
            )

            # Create workspace-specific agent executor
            agent_executor = self._create_agent_executor_for_workspace(workspace_id)

            # Extract service→repo mapping from context
            service_repo_mapping = (context or {}).get("service_repo_mapping", {})

            # Format the mapping for the prompt
            if service_repo_mapping:
                mapping_lines = [f"- Service `{service}` → Repository `{repo}`"
                                for service, repo in service_repo_mapping.items()]
                service_mapping_text = "\n".join(mapping_lines)
                logger.info(f"Injecting service→repo mapping with {len(service_repo_mapping)} entries")
            else:
                service_mapping_text = "(No services discovered - workspace may have no repositories)"
                logger.warning("No service→repo mapping provided in context")

            # Extract and format thread history from context
            thread_history = (context or {}).get("thread_history", [])

            if thread_history:
                logger.info(f"Formatting thread history with {len(thread_history)} messages")

                # Format thread messages as conversation history
                history_lines = ["## 🧵 CONVERSATION HISTORY", ""]
                history_lines.append("This is a follow-up question in an existing thread. Here's the previous conversation:")
                history_lines.append("")

                for msg in thread_history:
                    user_id = msg.get("user", "unknown")
                    text = msg.get("text", "")
                    bot_id = msg.get("bot_id")

                    # Strip bot mentions from message text (e.g., <@U12345678>)
                    clean_text = re.sub(settings.SLACK_USER_MENTION_PATTERN, "", text).strip()

                    # Identify if message is from bot or user
                    if bot_id:
                        history_lines.append(f"**Assistant**: {clean_text}")
                    else:
                        history_lines.append(f"**User ({user_id})**: {clean_text}")
                    history_lines.append("")

                thread_history_text = "\n".join(history_lines)
                logger.info("Thread history formatted and ready for injection")
            else:
                thread_history_text = ""
                logger.info("No thread history to format")

            # Check if there are images in the context
            files = (context or {}).get("files", [])
            images = []

            if files:
                logger.info(f"Detected {len(files)} files in message, processing images...")

                # Get Slack access token to download images
                team_id = (context or {}).get("team_id")
                if team_id:
                    from app.slack.service import slack_event_service
                    from app.utils.token_processor import token_processor

                    slack_installation = await slack_event_service.get_installation(team_id)
                    if slack_installation and slack_installation.access_token:
                        try:
                            access_token = token_processor.decrypt(slack_installation.access_token)
                            images = await self._download_slack_images(files, access_token)
                            logger.info(f"Downloaded {len(images)} images for Gemini processing")
                        except Exception as e:
                            logger.error(f"Failed to decrypt Slack access token for team {team_id}: {e}")
                            logger.warning("Proceeding with text-only analysis due to token decryption failure")
                            # Continue without images rather than failing the entire job
                    else:
                        logger.warning(f"No Slack installation or access token found for team {team_id}")

            # Prepare input for the agent
            # If images are present, we need to use multimodal message format
            if images:
                logger.info(f"Processing query with {len(images)} images using Gemini multimodal")

                # For LangChain with multimodal input, we need to bypass the agent
                # and directly call the LLM with HumanMessage containing images
                # since AgentExecutor doesn't support multimodal messages natively

                # We'll call the LLM directly with image content first to get visual analysis
                from langchain_core.messages import HumanMessage

                # Create multimodal content with text and images
                # Images must be base64-encoded per LangChain Gemini docs
                content_parts = [{"type": "text", "text": user_query}]

                for img in images:
                    try:
                        # Validate image can be opened (ensures it's a valid image)
                        with Image.open(io.BytesIO(img['data'])) as pil_image:
                            logger.info(
                                f"Validated {img['name']} as valid image "
                                f"(size: {pil_image.size}, mode: {pil_image.mode}, format: {pil_image.format})"
                            )

                        # Encode image to base64 for Gemini
                        encoded = self._encode_base64(img['data'])

                        # Format per LangChain docs: nested object with "url" key
                        # https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/use-cases/retrieval-augmented-generation/multimodal_rag_langchain.ipynb
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{img['mimetype']};base64,{encoded}"
                            }
                        })
                        logger.info(f"Encoded {img['name']} to base64 ({len(encoded)} chars)")
                    except Exception as e:
                        logger.error(f"Failed to process {img['name']}: {e}")
                        # Skip corrupted images rather than failing entire request
                        continue

                # Create HumanMessage with multimodal content
                multimodal_message = HumanMessage(content=content_parts)

                # Notify user that images are being processed (send to Slack via callback)
                if callbacks:
                    from app.services.rca.callbacks import SlackProgressCallback
                    for callback in callbacks:
                        if isinstance(callback, SlackProgressCallback):
                            await callback.send_image_processing_notification(len(images))
                            break

                # First, get image analysis from Gemini
                try:

                    logger.info("Sending multimodal message to Gemini for image analysis...")
                    image_analysis_response = await self.llm.ainvoke([multimodal_message])
                    image_analysis = image_analysis_response.content
                    logger.info(f"Gemini image analysis completed: {len(image_analysis)} chars")
                except Exception as e:
                    logger.error(f"Failed to analyze images with Gemini: {e}")
                    image_analysis = f"[Image analysis failed: {str(e)}]"

                # Now append the image analysis to the user query for the agent
                enhanced_query = (
                    f"{user_query}\n\n"
                    f"**Visual Analysis from {len(images)} attached image(s):**\n"
                    f"{image_analysis}\n\n"
                    f"Please use the above visual analysis along with your tools to provide a comprehensive RCA."
                )

                agent_input = {
                    "input": enhanced_query,
                    "service_mapping_text": service_mapping_text,
                    "thread_history_text": thread_history_text,
                }

            else:
                # Standard text-only input
                agent_input = {
                    "input": user_query,
                    "service_mapping_text": service_mapping_text,
                    "thread_history_text": thread_history_text,
                }

            # Execute the agent asynchronously with callbacks
            if callbacks:
                result = await agent_executor.ainvoke(agent_input, config={"callbacks": callbacks})
            else:
                result = await agent_executor.ainvoke(agent_input)

            logger.info(
                f"Gemini RCA analysis completed successfully for workspace: {workspace_id}"
            )

            return {
                "output": result.get(
                    "output", "Analysis completed but no output generated."
                ),
                "intermediate_steps": result.get("intermediate_steps", []),
                "success": True,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Error during Gemini RCA analysis: {e}", exc_info=True)
            return {
                "output": None,
                "intermediate_steps": [],
                "success": False,
                "error": f"RCA analysis failed: {str(e)}",
            }

    @staticmethod
    def _encode_base64(data: bytes) -> str:
        """Encode bytes to base64 string"""
        return base64.b64encode(data).decode('utf-8')

    async def analyze_with_retry(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
        callbacks: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Perform RCA analysis with automatic retry on failure

        Args:
            user_query: User's question
            context: Optional context
            max_retries: Maximum number of retry attempts
            callbacks: Optional callback handlers

        Returns:
            Analysis result dictionary
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self.analyze(user_query, context, callbacks=callbacks)

                if result["success"]:
                    return result

                # If analysis didn't succeed but didn't error, retry
                logger.warning(
                    f"Gemini analysis attempt {attempt + 1} did not succeed, retrying..."
                )

            except Exception as e:
                logger.error(f"Gemini attempt {attempt + 1} failed: {e}")

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

# Singleton instance
gemini_rca_agent_service = GeminiRCAAgentService()
