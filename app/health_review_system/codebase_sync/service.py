"""
CodebaseSyncService - Fetches repository HEAD and compares with previous review.
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.code_parser import CodeParserService
from app.github.tools.router import get_branch_recent_commits
from app.github.tools.service import get_default_branch
from app.health_review_system.codebase_sync.schemas import (
    CodebaseSyncResult,
    ParsedCodebaseInfo,
    ParsedFileInfo,
)
from app.models import Service, ServiceReview

logger = logging.getLogger(__name__)


class CodebaseSyncService:
    """
    Service for syncing codebase state for health reviews.

    Responsibilities:
    - Fetch HEAD commit SHA from GitHub
    - Compare with previous review's analyzed_commit_sha
    - Trigger parsing if code changed
    - Return parsed codebase data
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.code_parser = CodeParserService(db)

    async def sync(
        self,
        workspace_id: str,
        service: Service,
        previous_review: Optional[ServiceReview] = None,
    ) -> CodebaseSyncResult:
        """
        Sync codebase for a service.

        Args:
            workspace_id: Workspace ID
            service: Service model with repository info
            previous_review: Previous review for comparison (optional)

        Returns:
            CodebaseSyncResult with commit_sha, changed flag, and parsed data

        Raises:
            ValueError: If service has no repository linked
            RuntimeError: If failed to get HEAD SHA from GitHub
        """
        if not service.repository_name:
            raise ValueError(f"Service {service.id} has no repository linked")

        # Get current HEAD SHA from GitHub
        current_sha = await self._get_head_sha(workspace_id, service)

        if not current_sha:
            raise RuntimeError(
                f"Failed to get HEAD SHA for {service.repository_name}"
            )

        # Compare with previous review
        previous_sha = previous_review.analyzed_commit_sha if previous_review else None
        changed = current_sha != previous_sha

        # Get or parse codebase
        parsed_codebase = None
        if service.repository_name:
            parsed_data = await self.code_parser.get_or_parse_repository(
                workspace_id=workspace_id,
                installation_id=service.repository_id,  # Can be None, not used internally
                repo_full_name=service.repository_name,
                commit_sha=current_sha,
            )

            if parsed_data:
                # Fetch parsed files from DB and map to ParsedFileInfo
                parsed_files = await self._get_parsed_files(
                    workspace_id=workspace_id,
                    repo_full_name=service.repository_name,
                )

                parsed_codebase = ParsedCodebaseInfo(
                    files=parsed_files,
                    total_files=parsed_data.get("total_files", 0),
                    total_functions=parsed_data.get("total_functions", 0),
                    total_classes=parsed_data.get("total_classes", 0),
                    languages=parsed_data.get("languages", {}),
                )

        return CodebaseSyncResult(
            commit_sha=current_sha,
            changed=changed,
            parsed_codebase=parsed_codebase,
        )

    async def _get_head_sha(
        self,
        workspace_id: str,
        service: Service,
    ) -> Optional[str]:
        """
        Get HEAD commit SHA from GitHub using existing internal tools.

        Uses get_branch_recent_commits with rca-agent user to bypass verification.
        """
        if not service.repository_name:
            return None

        # Parse repository name (format: "owner/repo")
        parts = service.repository_name.split("/")
        if len(parts) != 2:
            logger.error(
                f"Invalid repository name format: {service.repository_name}. "
                "Expected 'owner/repo'"
            )
            return None

        owner, repo_name = parts

        try:
            logger.info(f"Fetching HEAD SHA for {service.repository_name}")

            # Get the default branch for the repository
            default_branch = await get_default_branch(
                workspace_id=workspace_id,
                repo_name=repo_name,
                owner=owner,
                db=self.db,
            )
            logger.info(f"Default branch for {owner}/{repo_name}: {default_branch}")

            # Use existing get_branch_recent_commits with rca-agent user
            result = await get_branch_recent_commits(
                workspace_id=workspace_id,
                name=repo_name,
                owner=owner,
                ref=f"refs/heads/{default_branch}",
                first=1,
                after=None,
                user_id="rca-agent",
                db=self.db,
            )

            # Extract commit SHA from the first commit
            commits = result.get("commits", [])
            if commits and len(commits) > 0:
                sha = commits[0].get("oid")
                if sha:
                    logger.info(f"Got HEAD SHA for {service.repository_name}: {sha[:8]}...")
                    return sha

            logger.warning(
                f"No commits found for {service.repository_name} on {default_branch} branch"
            )
            return None

        except Exception as e:
            logger.exception(
                f"Failed to get HEAD SHA for {service.repository_name}: {e}"
            )
            return None

    async def _get_parsed_files(
        self,
        workspace_id: str,
        repo_full_name: str,
        limit: int = 5000,
    ) -> list[ParsedFileInfo]:
        """
        Fetch parsed files from DB and map to ParsedFileInfo schema.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Full repository name (owner/repo)
            limit: Maximum number of files to fetch

        Returns:
            List of ParsedFileInfo objects with file paths and function/class names
        """
        try:
            # Use the code parser's repository to get parsed files
            from app.code_parser.repository import (
                ParsedFileRepository,
                ParsedRepositoryRepository,
            )

            repo_crud = ParsedRepositoryRepository(self.db)
            file_crud = ParsedFileRepository(self.db)

            # Get the latest parsed repository
            parsed_repo = await repo_crud.get_latest(workspace_id, repo_full_name)
            if not parsed_repo:
                logger.warning(f"No parsed repository found for {repo_full_name}")
                return []

            # Get all parsed files
            db_files = await file_crud.get_by_repository(parsed_repo.id, limit=limit)

            # Map to ParsedFileInfo schema
            parsed_files = []
            for db_file in db_files:
                # Extract function names from the functions JSON
                function_names = []
                if db_file.functions:
                    for func in db_file.functions:
                        if isinstance(func, dict) and "name" in func:
                            function_names.append(func["name"])

                # Extract class names from the classes JSON
                class_names = []
                if db_file.classes:
                    for cls in db_file.classes:
                        if isinstance(cls, dict) and "name" in cls:
                            class_names.append(cls["name"])

                parsed_files.append(
                    ParsedFileInfo(
                        path=db_file.file_path,
                        functions=function_names,
                        classes=class_names,
                    )
                )

            logger.info(
                f"Mapped {len(parsed_files)} parsed files for {repo_full_name}"
            )
            return parsed_files

        except Exception as e:
            logger.exception(f"Failed to get parsed files for {repo_full_name}: {e}")
            return []
