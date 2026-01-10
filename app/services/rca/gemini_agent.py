"""
RCA Agent Service using LangChain with Gemini LLM (supports multimodal inputs: text + images + videos)

Updated to use capability-based tool filtering:
- Tools are selected based on workspace integrations
- Only healthy integrations contribute tools
- Uses IntegrationCapabilityResolver and AgentExecutorBuilder
"""

import base64
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from .builder import AgentExecutorBuilder
from .capabilities import IntegrationCapabilityResolver
from .prompts import RCA_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class GeminiRCAAgentService:
    """
    Service for Root Cause Analysis using AI agent with Gemini (supports images and videos).

    Updated to use capability-based tool filtering:
    - Resolves workspace integrations to capabilities
    - Only loads tools for available, healthy integrations
    - Uses AgentExecutorBuilder for clean construction
    """

    def __init__(self):
        """Initialize the RCA agent with Gemini LLM (shared across all requests)"""
        self.llm = None
        self.prompt = None
        self.capability_resolver = IntegrationCapabilityResolver(only_healthy=True)
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

            # Create chat prompt template with system message, environment context, service mapping, and thread history
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        RCA_SYSTEM_PROMPT
                        + "\n\n{environment_context_text}"
                        + "\n\n## 📋 SERVICE→REPOSITORY MAPPING\n\n{service_mapping_text}\n\n{thread_history_text}",
                    ),
                    ("human", "{input}"),
                    ("placeholder", "{agent_scratchpad}"),
                ]
            )

            logger.info("Gemini RCA Agent LLM initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Gemini RCA agent LLM: {e}")
            raise

    def _format_environment_context(self, environment_context: Dict[str, Any]) -> str:
        """
        Format environment context for injection into the prompt.

        Args:
            environment_context: Dictionary containing:
                - environments: List of {name, is_default} dicts
                - default_environment: Name of the default environment
                - deployed_commits_by_environment: Dict of env_name -> {repo_full_name -> {commit_sha, deployed_at}}

        Returns:
            Formatted string for the prompt
        """
        if not environment_context:
            return "## 🌍 AVAILABLE ENVIRONMENTS\n\n(No environments configured - code will be read from HEAD)"

        environments = environment_context.get("environments", [])
        default_env = environment_context.get("default_environment")
        deployed_commits_by_env = environment_context.get(
            "deployed_commits_by_environment", {}
        )

        lines = ["## 🌍 AVAILABLE ENVIRONMENTS", ""]

        if environments:
            for env in environments:
                name = env.get("name", "unknown")
                is_default = env.get("is_default", False)
                suffix = " (default)" if is_default else ""
                lines.append(f"- `{name}`{suffix}")
        else:
            lines.append("(No environments configured)")

        if default_env:
            lines.append(
                f"\n**Default environment for investigation:** `{default_env}`"
            )

        if deployed_commits_by_env:
            lines.append("\n## 📦 DEPLOYED COMMITS BY ENVIRONMENT")
            lines.append("")
            lines.append(
                "Use these commit SHAs when reading repository code (pass as `ref` parameter to `download_file_tool`):"
            )

            total_commits = 0
            for env_name, commits in deployed_commits_by_env.items():
                # Find if this environment is the default
                is_default = any(
                    e.get("name") == env_name and e.get("is_default")
                    for e in environments
                )
                suffix = " (default)" if is_default else ""
                lines.append(f"\n**{env_name}**{suffix}:")

                if commits:
                    for repo, commit_info in commits.items():
                        if isinstance(commit_info, dict):
                            sha = commit_info.get("commit_sha", "HEAD")
                            deployed_at = commit_info.get("deployed_at", "unknown")
                            lines.append(
                                f"- `{repo}` → `{sha}` (deployed: {deployed_at})"
                            )
                        else:
                            # Handle legacy format where commit_info is just the sha string
                            lines.append(f"- `{repo}` → `{commit_info}`")
                        total_commits += 1
                else:
                    lines.append("- (No deployments recorded)")
        else:
            lines.append("\n## 📦 DEPLOYED COMMITS")
            lines.append("")
            lines.append("(No deployment data available - code will be read from HEAD)")
            total_commits = 0

        logger.info(
            f"Formatted environment context: {len(environments)} environments, "
            f"default={default_env}, {total_commits} total deployed commits across all environments"
        )

        return "\n".join(lines)

    async def _create_agent_executor_for_workspace(
        self,
        workspace_id: str,
        db: AsyncSession,
        service_mapping: Optional[Dict[str, str]] = None,
        thread_history: Optional[str] = None,
    ):
        """
        Create a workspace-specific agent executor with capability-filtered tools.

        This method:
        1. Resolves workspace integrations to capabilities
        2. Filters tools based on available capabilities
        3. Binds workspace_id to selected tools
        4. Creates the agent executor

        Args:
            workspace_id: The workspace ID
            db: Database session for querying integrations
            service_mapping: Optional service→repo mapping
            thread_history: Optional thread history

        Returns:
            AgentExecutor configured with capability-filtered tools
        """
        # Resolve capabilities from workspace integrations
        execution_context = await self.capability_resolver.resolve(
            workspace_id=workspace_id,
            db=db,
            service_mapping=service_mapping or {},
            thread_history=thread_history,
        )

        logger.info(
            f"Resolved capabilities for workspace {workspace_id}: "
            f"{[c.value for c in execution_context.capabilities]}"
        )
        logger.info(
            f"Active integrations: {list(execution_context.integrations.keys())}"
        )

        # Build agent executor with filtered tools
        builder = AgentExecutorBuilder(self.llm, self.prompt)
        executor = builder.with_context(execution_context).build()

        logger.info(
            f"Created Gemini agent executor for workspace {workspace_id} "
            f"with {len(executor.tools)} tools (capability-filtered)"
        )

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
                    logger.info(
                        f"Skipping non-image file: {file_obj.get('name')} ({mimetype})"
                    )
                    continue

                # Use url_private_download for direct download
                url_download = file_obj.get("url_private_download") or file_obj.get(
                    "url_private"
                )
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
                        if parsed.netloc and not parsed.netloc.startswith(
                            "files.slack.com"
                        ):
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
                        logger.info(
                            f"Following redirect ({redirect_count + 1}/{max_redirects}): {safe_url}"
                        )
                    else:
                        raise Exception(
                            f"Too many redirects (>{max_redirects}) while downloading {file_obj.get('name')}"
                        )

                    # Debug: Check what we actually downloaded
                    content_type = response.headers.get("content-type", "unknown")
                    first_bytes = (
                        response.content[:100]
                        if len(response.content) >= 100
                        else response.content
                    )

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

                    downloaded_images.append(
                        {
                            "name": file_obj.get("name", "image"),
                            "mimetype": mimetype,
                            "data": response.content,
                            "size": len(response.content),
                        }
                    )

                    logger.info(
                        f"Downloaded image: {file_obj.get('name')} ({len(response.content)} bytes)"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to download image {file_obj.get('name')}: {e}"
                    )

        return downloaded_images

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Perform root cause analysis for the given user query (supports images)

        Args:
            user_query: User's question or issue description (e.g., "Why is my xyz service slow?")
            context: Optional context from Slack (user_id, channel_id, workspace_id, files, etc.)
            callbacks: Optional list of callback handlers (e.g., for Slack progress updates)
            db: Database session for querying integrations (required for capability resolution)

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

            if not db:
                error_msg = (
                    "db session is required for capability-based tool resolution"
                )
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

            # Extract service→repo mapping from context
            service_repo_mapping = (context or {}).get("service_repo_mapping", {})

            # Format the mapping for the prompt
            if service_repo_mapping:
                mapping_lines = [
                    f"- Service `{service}` → Repository `{repo}`"
                    for service, repo in service_repo_mapping.items()
                ]
                service_mapping_text = "\n".join(mapping_lines)
                logger.info(
                    f"Injecting service→repo mapping with {len(service_repo_mapping)} entries"
                )
            else:
                service_mapping_text = (
                    "(No services discovered - workspace may have no repositories)"
                )
                logger.warning("No service→repo mapping provided in context")

            # Extract and format environment context
            environment_context = (context or {}).get("environment_context", {})
            environment_context_text = self._format_environment_context(
                environment_context
            )

            # Extract and format thread history from context
            thread_history = (context or {}).get("thread_history", [])

            if thread_history:
                logger.info(
                    f"Formatting thread history with {len(thread_history)} messages"
                )

                # Format thread messages as conversation history
                history_lines = ["## 🧵 CONVERSATION HISTORY", ""]
                history_lines.append(
                    "This is a follow-up question in an existing thread. Here's the previous conversation:"
                )
                history_lines.append("")

                for msg in thread_history:
                    user_id = msg.get("user", "unknown")
                    text = msg.get("text", "")
                    bot_id = msg.get("bot_id")

                    # Strip bot mentions from message text (e.g., <@U12345678>)
                    clean_text = re.sub(
                        settings.SLACK_USER_MENTION_PATTERN, "", text
                    ).strip()

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

            # Create workspace-specific agent executor with capability-filtered tools
            agent_executor = await self._create_agent_executor_for_workspace(
                workspace_id=workspace_id,
                db=db,
                service_mapping=service_repo_mapping,
                thread_history=thread_history_text,
            )

            # Check if there are files in the context
            files = (context or {}).get("files", [])
            media_files = []

            if files:
                logger.info(f"Detected {len(files)} file(s) in message, processing...")

                # Get Slack access token to download images
                team_id = (context or {}).get("team_id")
                if team_id:
                    from app.slack.service import slack_event_service
                    from app.utils.token_processor import token_processor

                    slack_installation = await slack_event_service.get_installation(
                        team_id
                    )
                    if slack_installation and slack_installation.access_token:
                        try:
                            access_token = token_processor.decrypt(
                                slack_installation.access_token
                            )
                            media_files = await self._download_slack_images(
                                files, access_token
                            )
                            logger.info(
                                f"Downloaded {len(media_files)} file(s) for Gemini processing"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to decrypt Slack access token for team {team_id}: {e}"
                            )
                            logger.warning(
                                "Proceeding with text-only analysis due to token decryption failure"
                            )
                            # Continue without images rather than failing the entire job
                    else:
                        logger.warning(
                            f"No Slack installation or access token found for team {team_id}"
                        )
                else:
                    # Web files: Download from S3 and send directly to Gemini
                    # Gemini handles all file types the same way - just bytes + MIME type
                    logger.info("Processing web-uploaded files from context")
                    import base64

                    import magic

                    from app.services.s3.client import s3_client
                    from app.services.storage.file_validator import FileValidator

                    for file_info in files:
                        filename = file_info.get("filename", "unknown")
                        mime_type = file_info.get(
                            "mime_type", "application/octet-stream"
                        )
                        s3_key = file_info.get("s3_key")
                        file_size = file_info.get("size", 0)

                        # Skip very large files to prevent memory exhaustion
                        if file_size > settings.MAX_GEMINI_FILE_SIZE_BYTES:
                            logger.warning(
                                f"Skipping '{filename}' ({file_size / (1024 * 1024):.1f}MB) - "
                                f"exceeds {settings.MAX_GEMINI_FILE_SIZE_BYTES / (1024 * 1024):.0f}MB limit for Gemini processing. "
                                f"Using extracted text instead if available."
                            )
                            # Fall through to extracted_text handling below
                            if file_info.get("extracted_text"):
                                extracted_text = file_info["extracted_text"]
                                user_query += f"\n\n**File: {filename}** (large file - text only)\n```\n{extracted_text}\n```"
                                logger.info(
                                    f"Used extracted text for large file '{filename}'"
                                )
                            continue

                        if s3_key:
                            # Download from S3 and send to Gemini
                            try:
                                logger.info(
                                    f"Downloading '{filename}' from S3 (key: {s3_key})"
                                )
                                file_bytes = await s3_client.download_file(s3_key)

                                if file_bytes:
                                    # Re-validate MIME type after download for security
                                    # This prevents processing of malicious files if job context was compromised
                                    try:
                                        actual_mime = magic.from_buffer(
                                            file_bytes, mime=True
                                        )
                                        file_category = (
                                            FileValidator.get_category_from_mime(
                                                actual_mime
                                            )
                                        )

                                        # Verify actual MIME matches expected MIME type category
                                        expected_category = (
                                            FileValidator.get_category_from_mime(
                                                mime_type
                                            )
                                        )
                                        if file_category != expected_category:
                                            logger.warning(
                                                f"⚠️ MIME type mismatch for '{filename}': "
                                                f"expected {mime_type} ({expected_category}), "
                                                f"got {actual_mime} ({file_category}). Skipping file."
                                            )
                                            continue

                                        # Use actual detected MIME type
                                        mime_type = actual_mime
                                        logger.info(
                                            f"✓ MIME type validated: '{filename}' is {actual_mime}"
                                        )
                                    except Exception as mime_error:
                                        logger.error(
                                            f"✗ MIME validation failed for '{filename}': {mime_error}. Skipping file."
                                        )
                                        continue

                                    media_files.append(
                                        {
                                            "name": filename,
                                            "mimetype": mime_type,
                                            "data": file_bytes,
                                            "size": len(file_bytes),
                                        }
                                    )
                                    logger.info(
                                        f"✓ Downloaded '{filename}' ({len(file_bytes)} bytes, {mime_type})"
                                    )
                                else:
                                    logger.error(
                                        f"✗ Failed to download '{filename}' from S3"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"✗ Exception downloading '{filename}': {e}",
                                    exc_info=True,
                                )

                        elif file_info.get("data"):
                            # Legacy: base64-encoded file data
                            try:
                                file_bytes = base64.b64decode(file_info["data"])
                                media_files.append(
                                    {
                                        "name": filename,
                                        "mimetype": mime_type,
                                        "data": file_bytes,
                                        "size": len(file_bytes),
                                    }
                                )
                                logger.info(
                                    f"✓ Decoded legacy base64 '{filename}' ({len(file_bytes)} bytes)"
                                )
                            except Exception as e:
                                logger.error(
                                    f"✗ Failed to decode '{filename}': {e}",
                                    exc_info=True,
                                )

                        elif file_info.get("extracted_text"):
                            # Fallback: append extracted text to query (legacy)
                            extracted_text = file_info["extracted_text"]
                            user_query += (
                                f"\n\n**File: {filename}**\n```\n{extracted_text}\n```"
                            )
                            logger.info(
                                f"Appended {len(extracted_text)} chars from '{filename}' to query"
                            )

                        else:
                            logger.error(
                                f"✗ No S3 key, data, or extracted text for '{filename}'"
                            )

                    if media_files:
                        logger.info(
                            f"Loaded {len(media_files)} file(s) for Gemini processing"
                        )

            # Prepare input for the agent
            # If files are present, use multimodal message format
            if media_files:
                logger.info(
                    f"Processing query with {len(media_files)} file(s) using Gemini multimodal"
                )

                # For LangChain with multimodal input, we bypass the agent
                # and directly call the LLM with HumanMessage containing files
                from langchain_core.messages import HumanMessage

                # Enhance user query to mention attached files
                file_names = [f["name"] for f in media_files]
                media_context = f"\n\n**IMPORTANT: The user has attached {len(media_files)} file(s): {', '.join(file_names)}. Please analyze these files carefully as they contain relevant information for answering the question.**"
                enhanced_query = user_query + media_context

                # Create multimodal content with text and files
                # Files must be base64-encoded per LangChain Gemini docs
                content_parts = [{"type": "text", "text": enhanced_query}]

                for media in media_files:
                    try:
                        # Encode file to base64 for Gemini
                        encoded = self._encode_base64(media["data"])
                        mimetype = media["mimetype"]

                        # Use "media" type for all files (images, PDFs, videos, etc.)
                        # LangChain ChatGoogleGenerativeAI supports this format for all file types
                        content_parts.append(
                            {
                                "type": "media",
                                "data": encoded,
                                "mime_type": mimetype,
                            }
                        )

                        logger.info(
                            f"Encoded '{media['name']}' ({mimetype}) to base64 ({len(encoded)} chars)"
                        )
                    except Exception as e:
                        logger.error(f"Failed to encode '{media['name']}': {e}")
                        continue

                # Create HumanMessage with multimodal content
                multimodal_message = HumanMessage(content=content_parts)

                # Notify user that files are being processed (send to Slack via callback)
                if callbacks:
                    from app.services.rca.callbacks import SlackProgressCallback

                    for callback in callbacks:
                        if isinstance(callback, SlackProgressCallback):
                            await callback.send_image_processing_notification(
                                len(media_files)
                            )
                            break

                # Get file analysis from Gemini
                try:
                    logger.info("Sending multimodal message to Gemini for analysis...")
                    file_analysis_response = await self.llm.ainvoke(
                        [multimodal_message]
                    )
                    file_analysis = file_analysis_response.content
                    logger.info(
                        f"Gemini analysis completed: {len(file_analysis)} chars"
                    )
                except Exception as e:
                    logger.error(f"Failed to analyze files with Gemini: {e}")
                    file_analysis = f"[File analysis failed: {str(e)}]"

                # Now append the file analysis to the user query for the agent
                enhanced_query = (
                    f"{user_query}\n\n"
                    f"**Analysis of {len(media_files)} attached file(s):**\n"
                    f"{file_analysis}\n\n"
                    f"Please use the above file analysis along with your tools to provide a comprehensive RCA."
                )

                agent_input = {
                    "input": enhanced_query,
                    "environment_context_text": environment_context_text,
                    "service_mapping_text": service_mapping_text,
                    "thread_history_text": thread_history_text,
                }

            else:
                # Standard text-only input
                agent_input = {
                    "input": user_query,
                    "environment_context_text": environment_context_text,
                    "service_mapping_text": service_mapping_text,
                    "thread_history_text": thread_history_text,
                }

            # Log context details before LLM API call for debugging context length issues
            # Model context windows: llama-3.3-70b-versatile = 128K tokens, gemini-2.0-flash-exp = 1M tokens
            system_prompt_len = len(RCA_SYSTEM_PROMPT)
            environment_context_len = len(environment_context_text)
            thread_history_len = len(thread_history_text)
            service_mapping_len = len(service_mapping_text)
            user_query_len = len(
                agent_input["input"]
            )  # Use actual input (may include image analysis)
            total_chars = (
                system_prompt_len
                + environment_context_len
                + thread_history_len
                + service_mapping_len
                + user_query_len
            )

            # Rough token estimate (1 token ≈ 4 characters for English text)
            estimated_tokens = total_chars // 4

            logger.info(
                f"📊 Context size before LLM call (model: {settings.GEMINI_LLM_MODEL}):\n"
                f"  - System prompt: {system_prompt_len} chars\n"
                f"  - Environment context: {environment_context_len} chars\n"
                f"  - Thread history: {thread_history_len} chars ({len(thread_history)} messages)\n"
                f"  - Service mapping: {service_mapping_len} chars ({len(service_repo_mapping)} services)\n"
                f"  - User query (with images if any): {user_query_len} chars\n"
                f"  - Total input: {total_chars} chars (~{estimated_tokens} tokens est.)\n"
                f"  - Max output tokens: {settings.RCA_AGENT_MAX_TOKENS}"
            )

            # Record LLM context and token metrics
            from app.core.otel_metrics import LLM_METRICS

            context_size_bytes = (
                len(environment_context_text.encode("utf-8"))
                + len(thread_history_text.encode("utf-8"))
                + len(service_mapping_text.encode("utf-8"))
                + len(agent_input["input"].encode("utf-8"))
            )

            LLM_METRICS["rca_context_size_bytes"].record(
                context_size_bytes,
                {
                    "model": settings.GEMINI_LLM_MODEL,
                },
            )

            LLM_METRICS["rca_estimated_input_tokens"].record(
                estimated_tokens,
                {
                    "model": settings.GEMINI_LLM_MODEL,
                },
            )

            # Record LLM provider usage
            LLM_METRICS["rca_llm_provider_usage_total"].add(
                1,
                {
                    "model": settings.GEMINI_LLM_MODEL,
                },
            )

            # Execute the agent asynchronously with callbacks
            if callbacks:
                result = await agent_executor.ainvoke(
                    agent_input, config={"callbacks": callbacks}
                )
            else:
                result = await agent_executor.ainvoke(agent_input)

            logger.info(
                f"Gemini RCA analysis completed successfully for workspace: {workspace_id}"
            )

            output = result.get("output", "Analysis completed but no output generated.")

            # Handle LangChain's max iterations message - provide a better response
            if "stopped due to" in output.lower() and (
                "iteration" in output.lower() or "time limit" in output.lower()
            ):
                logger.warning(
                    f"Agent hit iteration/time limit for workspace {workspace_id}"
                )
                # Provide a more helpful message to the user
                output = (
                    "I gathered some information but couldn't complete the full analysis "
                    "within the allowed processing time. Here's what I found so far:\n\n"
                    "Please try asking a more specific question, or break down your request "
                    "into smaller parts for better results."
                )

            return {
                "output": output,
                "intermediate_steps": result.get("intermediate_steps", []),
                "success": True,
                "error": None,
            }

        except Exception as e:
            # Enhanced error logging for Gemini API errors
            error_details = {"error_type": type(e).__name__, "error_message": str(e)}
            is_context_length_error = False

            # Check for context_length_exceeded or quota errors in Gemini
            error_str = str(e).lower()
            if (
                "context_length" in error_str
                or "quota" in error_str
                or "resource" in error_str
            ):
                is_context_length_error = True

            # Special logging for context_length_exceeded errors
            if is_context_length_error:
                # Log complete context details for debugging
                logger.error(
                    f"🚨 CONTEXT/QUOTA ERROR DETECTED IN GEMINI 🚨\n"
                    f"Model: {settings.GEMINI_LLM_MODEL}\n"
                    f"Max output tokens configured: {settings.RCA_AGENT_MAX_TOKENS}\n"
                    f"System prompt length: {len(RCA_SYSTEM_PROMPT)} chars\n"
                    f"Environment context length: {len(environment_context_text)} chars\n"
                    f"Thread history length: {len(thread_history_text)} chars\n"
                    f"Service mapping length: {len(service_mapping_text)} chars\n"
                    f"User query length: {len(user_query)} chars\n"
                    f"Error details: {error_details}"
                )
                error_details["is_context_length_error"] = True

            logger.error(
                f"Error during Gemini RCA analysis: {error_details}", exc_info=True
            )
            return {
                "output": None,
                "intermediate_steps": [],
                "success": False,
                "error": f"RCA analysis failed: {str(e)}",
                "error_details": error_details,  # Include error details for fallback logic
            }

    @staticmethod
    def _encode_base64(data: bytes) -> str:
        """Encode bytes to base64 string"""
        return base64.b64encode(data).decode("utf-8")

    async def analyze_with_retry(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Perform RCA analysis with automatic retry on failure

        Args:
            user_query: User's question
            context: Optional context
            max_retries: Maximum number of retry attempts
            callbacks: Optional callback handlers
            db: Database session for querying integrations (required)

        Returns:
            Analysis result dictionary
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self.analyze(
                    user_query, context, callbacks=callbacks, db=db
                )

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
