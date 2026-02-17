"""
CodeParserService - Main service for parsing codebases.

Orchestrates fetching repository files from GitHub, parsing them with
language-specific parsers, and storing results in the database.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.github.tools.router import (
    fetch_files_batch,
    get_repository_tree_recursive,
)
from app.github.tools.service import get_default_branch
from app.models import ParsingStatus

from .parsers import get_parser_registry
from .parsers.constants import (
    get_file_extension,
    get_language_for_file,
    is_code_file,
    is_supported_file,
    should_skip_file,
)
from .repository import ParsedFileRepository, ParsedRepositoryRepository

logger = logging.getLogger(__name__)

# Special user ID for system operations (bypasses user verification)
RCA_AGENT_USER_ID = "rca-agent"


class CodeParserService:
    """
    Service for parsing codebases and storing results in the database.

    This service:
    1. Fetches repository file tree from GitHub
    2. Filters files by supported extensions
    3. Batch fetches file contents
    4. Parses each file with the appropriate language parser
    5. Stores everything in the database for fast LLM access
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo_crud = ParsedRepositoryRepository(db)
        self.file_crud = ParsedFileRepository(db)
        self.parser_registry = get_parser_registry()

    async def get_parsed_repository(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached parsed repository data.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Optional specific commit SHA (if not provided, gets latest)

        Returns:
            Parsed repository data or None if not cached
        """
        if commit_sha:
            parsed_repo = await self.repo_crud.get_by_commit(
                workspace_id, repo_full_name, commit_sha
            )
        else:
            parsed_repo = await self.repo_crud.get_latest(workspace_id, repo_full_name)

        if not parsed_repo:
            return None

        if parsed_repo.status != ParsingStatus.COMPLETED:
            logger.info(f"Found incomplete parse for {repo_full_name}: status={parsed_repo.status}")
            return None

        # Get file count for response
        files = await self.file_crud.get_by_repository(parsed_repo.id, limit=10000)

        return {
            "id": parsed_repo.id,
            "workspace_id": parsed_repo.workspace_id,
            "repo_full_name": parsed_repo.repo_full_name,
            "commit_sha": parsed_repo.commit_sha,
            "default_branch": parsed_repo.default_branch,
            "status": parsed_repo.status.value,
            "total_files": parsed_repo.total_files,
            "parsed_files": parsed_repo.parsed_files,
            "skipped_files": parsed_repo.skipped_files,
            "total_functions": parsed_repo.total_functions,
            "total_classes": parsed_repo.total_classes,
            "total_imports": parsed_repo.total_imports,
            "languages": parsed_repo.languages or {},
            "files_count": len(files),
            "created_at": parsed_repo.created_at.isoformat() if parsed_repo.created_at else None,
            "completed_at": parsed_repo.completed_at.isoformat() if parsed_repo.completed_at else None,
        }

    async def parse_repository(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        default_branch: Optional[str] = None,
        concurrency: int = 10,
        service_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Parse a repository and cache the results.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Git commit SHA to parse
            default_branch: Default branch name (will be fetched if not provided)
            concurrency: Number of concurrent file fetches
            service_id: Service ID (for cascade delete on service removal)

        Returns:
            Parsed repository data
        """
        # Parse owner/repo from full name
        parts = repo_full_name.split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid repo_full_name format: {repo_full_name}")
        owner, name = parts

        logger.info(f"Starting repository parse for {repo_full_name}@{commit_sha[:8]}")

        # Get default branch if not provided
        if not default_branch:
            try:
                default_branch = await get_default_branch(workspace_id, name, owner, self.db)
            except Exception as e:
                logger.warning(f"Failed to get default branch: {e}, using 'main'")
                default_branch = "main"

        # Create ParsedRepository record with PENDING status
        parsed_repo = await self.repo_crud.create(
            workspace_id=workspace_id,
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            default_branch=default_branch,
            service_id=service_id,
        )

        try:
            # Update status to IN_PROGRESS
            await self.repo_crud.update_status(parsed_repo.id, ParsingStatus.IN_PROGRESS)

            # Step 1: Get repository file tree
            logger.info(f"Fetching file tree for {repo_full_name}")
            file_tree = await get_repository_tree_recursive(
                workspace_id=workspace_id,
                name=name,
                owner=owner,
                branch=commit_sha,  # Use commit SHA for exact version
                user_id=RCA_AGENT_USER_ID,
                db=self.db,
            )

            if not file_tree:
                logger.warning(f"No files found in repository {repo_full_name}")
                await self.repo_crud.update_status(
                    parsed_repo.id,
                    ParsingStatus.COMPLETED,
                    stats={"total_files": 0, "parsed_files": 0, "skipped_files": 0},
                )
                return await self.get_parsed_repository(workspace_id, repo_full_name, commit_sha)

            # Step 2: Filter files
            supported_files = []
            skipped_files = []
            skipped_extensions = {}  # Track skipped file extensions

            for file_entry in file_tree:
                file_path = file_entry.get("path", "")
                file_size = file_entry.get("size", 0)

                if should_skip_file(file_path, file_size):
                    skipped_files.append(file_path)
                    ext = get_file_extension(file_path)
                    skipped_extensions[ext] = skipped_extensions.get(ext, 0) + 1
                    continue

                if is_supported_file(file_path):
                    supported_files.append(file_entry)
                else:
                    skipped_files.append(file_path)
                    ext = get_file_extension(file_path)
                    skipped_extensions[ext] = skipped_extensions.get(ext, 0) + 1

            logger.info(
                f"Found {len(supported_files)} supported files, "
                f"skipping {len(skipped_files)} files"
            )
            if skipped_extensions:
                logger.info(f"Skipped extensions: {skipped_extensions}")

            # Step 3: Batch fetch file contents
            file_paths = [f["path"] for f in supported_files]

            logger.info(f"Fetching {len(file_paths)} file contents")
            fetched_files = await fetch_files_batch(
                workspace_id=workspace_id,
                name=name,
                owner=owner,
                file_paths=file_paths,
                branch=commit_sha,
                user_id=RCA_AGENT_USER_ID,
                db=self.db,
                concurrency=concurrency,
            )

            # Step 4: Parse each file
            parsed_files_data = []
            parse_errors = []
            languages_count = {}
            total_functions = 0
            total_classes = 0
            total_imports = 0

            for fetched in fetched_files:
                file_path = fetched["path"]
                content = fetched.get("content")

                if not fetched.get("success") or not content:
                    # Skip files that failed to fetch
                    parse_errors.append({
                        "file": file_path,
                        "error": fetched.get("error", "Failed to fetch content"),
                    })
                    continue

                # Get language
                language = get_language_for_file(file_path)
                if not language:
                    continue

                # Check if this is a code file (has a parser) or config file (content only)
                if is_code_file(file_path):
                    parser = self.parser_registry.get_parser(language)
                    if not parser:
                        continue

                    # Parse the code file
                    try:
                        parse_result = parser.parse(content, file_path)
                        functions_list = [f.model_dump() for f in parse_result.functions]
                        classes_list = [c.model_dump() for c in parse_result.classes]
                        imports_list = [i.model_dump() for i in parse_result.imports]
                        line_count = parse_result.line_count
                        is_parsed = not parse_result.parse_error
                        parse_error = parse_result.parse_error

                        if parse_result.parse_error:
                            parse_errors.append({
                                "file": file_path,
                                "error": parse_result.parse_error,
                            })
                    except Exception as e:
                        logger.error(f"Error parsing {file_path}: {e}")
                        parse_errors.append({
                            "file": file_path,
                            "error": str(e),
                        })
                        continue
                else:
                    # Config file - store content only, no parsing
                    functions_list = []
                    classes_list = []
                    imports_list = []
                    line_count = content.count("\n") + 1
                    is_parsed = True
                    parse_error = None

                # Create parsed file record
                parsed_file = {
                    "file_path": file_path,
                    "language": language,
                    "content": content,
                    "size_bytes": len(content.encode("utf-8")),
                    "line_count": line_count,
                    "functions": functions_list,
                    "classes": classes_list,
                    "imports": imports_list,
                    "is_parsed": is_parsed,
                    "parse_error": parse_error,
                }

                parsed_files_data.append(parsed_file)

                # Update counts
                languages_count[language] = languages_count.get(language, 0) + 1
                total_functions += len(functions_list)
                total_classes += len(classes_list)
                total_imports += len(imports_list)

            # Step 5: Store parsed files in database
            if parsed_files_data:
                await self.file_crud.create_batch(parsed_repo.id, parsed_files_data)

            # Step 6: Update repository status to COMPLETED
            stats = {
                "total_files": len(file_tree),
                "parsed_files": len(parsed_files_data),
                "skipped_files": len(skipped_files),
                "total_functions": total_functions,
                "total_classes": total_classes,
                "total_imports": total_imports,
                "languages": languages_count,
                "parse_errors": parse_errors[:100],  # Limit stored errors
            }

            await self.repo_crud.update_status(parsed_repo.id, ParsingStatus.COMPLETED, stats=stats)

            logger.info(
                f"Completed parsing {repo_full_name}: "
                f"{len(parsed_files_data)} files, "
                f"{total_functions} functions, "
                f"{total_classes} classes"
            )

            # Clean up old parses (keep last 3)
            await self.repo_crud.delete_old_parses(workspace_id, repo_full_name, keep_count=3)

            return await self.get_parsed_repository(workspace_id, repo_full_name, commit_sha)

        except Exception as e:
            logger.error(f"Failed to parse repository {repo_full_name}: {e}")
            await self.repo_crud.update_status(
                parsed_repo.id,
                ParsingStatus.FAILED,
                error_message=str(e),
            )
            raise

    async def get_or_parse_repository(
        self,
        workspace_id: str,
        installation_id: str,
        repo_full_name: str,
        commit_sha: str,
        service_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get cached parse or trigger new parse if needed.

        This is the main entry point for the health review system.

        Args:
            workspace_id: Workspace ID
            installation_id: GitHub installation ID (not used directly, kept for compatibility)
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Current HEAD commit SHA
            service_id: Service ID (for cascade delete on service removal)

        Returns:
            Parsed codebase data with 'changed' flag
        """
        # Check cache first
        cached = await self.get_parsed_repository(workspace_id, repo_full_name, commit_sha)

        if cached:
            logger.info(f"Using cached parse for {repo_full_name}@{commit_sha[:8]}")
            return {
                **cached,
                "changed": False,
            }

        # Parse and cache
        logger.info(f"No cache found, parsing {repo_full_name}@{commit_sha[:8]}")
        parsed = await self.parse_repository(workspace_id, repo_full_name, commit_sha, service_id=service_id)

        return {
            **parsed,
            "changed": True,
        }

    async def get_file_content(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
    ) -> Optional[str]:
        """
        Get file content from the database.

        This is a fast alternative to calling GitHub API for files
        that have already been parsed.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            file_path: File path within the repository

        Returns:
            File content or None if not found
        """
        # Get the latest parsed repository
        parsed_repo = await self.repo_crud.get_latest(workspace_id, repo_full_name)
        if not parsed_repo:
            return None

        # Get file content
        return await self.file_crud.get_content(parsed_repo.id, file_path)

    async def search_function(
        self,
        workspace_id: str,
        repo_full_name: str,
        function_name: str,
        exact_match: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search for a function by name across all files.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            function_name: Function name to search for
            exact_match: If True, require exact name match

        Returns:
            List of matching functions with file info
        """
        parsed_repo = await self.repo_crud.get_latest(workspace_id, repo_full_name)
        if not parsed_repo:
            return []

        return await self.file_crud.search_functions(parsed_repo.id, function_name, exact_match)

    async def search_class(
        self,
        workspace_id: str,
        repo_full_name: str,
        class_name: str,
        exact_match: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search for a class by name across all files.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            class_name: Class name to search for
            exact_match: If True, require exact name match

        Returns:
            List of matching classes with file info
        """
        parsed_repo = await self.repo_crud.get_latest(workspace_id, repo_full_name)
        if not parsed_repo:
            return []

        return await self.file_crud.search_classes(parsed_repo.id, class_name, exact_match)

    async def get_file_structure(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get file structure (functions, classes, imports) without content.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            file_path: File path within the repository

        Returns:
            File structure or None if not found
        """
        parsed_repo = await self.repo_crud.get_latest(workspace_id, repo_full_name)
        if not parsed_repo:
            return None

        parsed_file = await self.file_crud.get_by_path(parsed_repo.id, file_path)
        if not parsed_file:
            return None

        return {
            "file_path": parsed_file.file_path,
            "language": parsed_file.language,
            "line_count": parsed_file.line_count,
            "functions": parsed_file.functions or [],
            "classes": parsed_file.classes or [],
            "imports": parsed_file.imports or [],
        }

    async def list_files(
        self,
        workspace_id: str,
        repo_full_name: str,
        language: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        List all parsed files for a repository.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            language: Optional language filter
            limit: Maximum number of results

        Returns:
            List of file info dictionaries
        """
        parsed_repo = await self.repo_crud.get_latest(workspace_id, repo_full_name)
        if not parsed_repo:
            return []

        files = await self.file_crud.get_by_repository(parsed_repo.id, language=language, limit=limit)

        return [
            {
                "file_path": f.file_path,
                "language": f.language,
                "line_count": f.line_count,
                "function_count": len(f.functions or []),
                "class_count": len(f.classes or []),
            }
            for f in files
        ]
