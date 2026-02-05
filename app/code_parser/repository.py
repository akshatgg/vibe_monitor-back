"""
Database repository layer for code parser module.

Provides CRUD operations for ParsedRepository and ParsedFile models.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ParsedFile, ParsedRepository, ParsingStatus

logger = logging.getLogger(__name__)


class ParsedRepositoryRepository:
    """CRUD operations for ParsedRepository model."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, repository_id: str) -> Optional[ParsedRepository]:
        """Get a parsed repository by ID."""
        result = await self.db.execute(
            select(ParsedRepository).where(ParsedRepository.id == repository_id)
        )
        return result.scalar_one_or_none()

    async def get_by_commit(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
    ) -> Optional[ParsedRepository]:
        """
        Get a parsed repository by workspace, repo name, and commit SHA.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Full repository name (owner/repo)
            commit_sha: Git commit SHA

        Returns:
            ParsedRepository if found, None otherwise
        """
        result = await self.db.execute(
            select(ParsedRepository).where(
                and_(
                    ParsedRepository.workspace_id == workspace_id,
                    ParsedRepository.repo_full_name == repo_full_name,
                    ParsedRepository.commit_sha == commit_sha,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(
        self,
        workspace_id: str,
        repo_full_name: str,
    ) -> Optional[ParsedRepository]:
        """
        Get the most recently parsed version of a repository.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Full repository name (owner/repo)

        Returns:
            Most recent ParsedRepository or None
        """
        result = await self.db.execute(
            select(ParsedRepository)
            .where(
                and_(
                    ParsedRepository.workspace_id == workspace_id,
                    ParsedRepository.repo_full_name == repo_full_name,
                    ParsedRepository.status == ParsingStatus.COMPLETED,
                )
            )
            .order_by(ParsedRepository.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        default_branch: Optional[str] = None,
    ) -> ParsedRepository:
        """
        Create a new parsed repository record.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Full repository name (owner/repo)
            commit_sha: Git commit SHA
            default_branch: Default branch name

        Returns:
            Created ParsedRepository
        """
        parsed_repo = ParsedRepository(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            default_branch=default_branch,
            status=ParsingStatus.PENDING,
            total_files=0,
            parsed_files=0,
            skipped_files=0,
            total_functions=0,
            total_classes=0,
            total_imports=0,
            languages={},
            parse_errors=[],
            started_at=datetime.now(timezone.utc),
        )

        self.db.add(parsed_repo)
        await self.db.flush()

        logger.info(f"Created ParsedRepository {parsed_repo.id} for {repo_full_name}@{commit_sha[:8]}")
        return parsed_repo

    async def update_status(
        self,
        repository_id: str,
        status: ParsingStatus,
        stats: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ParsedRepository]:
        """
        Update the status and stats of a parsed repository.

        Args:
            repository_id: Repository ID
            status: New status
            stats: Optional dictionary of stats to update
            error_message: Optional error message (for FAILED status)

        Returns:
            Updated ParsedRepository or None if not found
        """
        update_values = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }

        if status == ParsingStatus.COMPLETED:
            update_values["completed_at"] = datetime.now(timezone.utc)

        if status == ParsingStatus.IN_PROGRESS:
            update_values["started_at"] = datetime.now(timezone.utc)

        if error_message:
            update_values["error_message"] = error_message

        if stats:
            update_values.update(stats)

        await self.db.execute(
            update(ParsedRepository)
            .where(ParsedRepository.id == repository_id)
            .values(**update_values)
        )
        await self.db.flush()

        return await self.get_by_id(repository_id)

    async def delete_old_parses(
        self,
        workspace_id: str,
        repo_full_name: str,
        keep_count: int = 3,
    ) -> int:
        """
        Delete old parsed repository records, keeping the most recent ones.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Full repository name
            keep_count: Number of recent records to keep

        Returns:
            Number of deleted records
        """
        # Get IDs of records to keep
        result = await self.db.execute(
            select(ParsedRepository.id)
            .where(
                and_(
                    ParsedRepository.workspace_id == workspace_id,
                    ParsedRepository.repo_full_name == repo_full_name,
                )
            )
            .order_by(ParsedRepository.created_at.desc())
            .limit(keep_count)
        )
        keep_ids = [row[0] for row in result.fetchall()]

        if not keep_ids:
            return 0

        # Delete older records (cascade will delete associated files)
        result = await self.db.execute(
            delete(ParsedRepository).where(
                and_(
                    ParsedRepository.workspace_id == workspace_id,
                    ParsedRepository.repo_full_name == repo_full_name,
                    ~ParsedRepository.id.in_(keep_ids),
                )
            )
        )

        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old parsed repositories for {repo_full_name}")

        return deleted_count


class ParsedFileRepository:
    """CRUD operations for ParsedFile model."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, file_id: str) -> Optional[ParsedFile]:
        """Get a parsed file by ID."""
        result = await self.db.execute(
            select(ParsedFile).where(ParsedFile.id == file_id)
        )
        return result.scalar_one_or_none()

    async def get_by_path(
        self,
        repository_id: str,
        file_path: str,
    ) -> Optional[ParsedFile]:
        """
        Get a parsed file by repository ID and path.

        Args:
            repository_id: ParsedRepository ID
            file_path: File path within the repository

        Returns:
            ParsedFile if found, None otherwise
        """
        result = await self.db.execute(
            select(ParsedFile).where(
                and_(
                    ParsedFile.repository_id == repository_id,
                    ParsedFile.file_path == file_path,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_repository(
        self,
        repository_id: str,
        language: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[ParsedFile]:
        """
        Get all parsed files for a repository.

        Args:
            repository_id: ParsedRepository ID
            language: Optional language filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of ParsedFile records
        """
        query = select(ParsedFile).where(ParsedFile.repository_id == repository_id)

        if language:
            query = query.where(ParsedFile.language == language)

        query = query.order_by(ParsedFile.file_path).limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_content(
        self,
        repository_id: str,
        file_path: str,
    ) -> Optional[str]:
        """
        Get file content by repository ID and path.

        Args:
            repository_id: ParsedRepository ID
            file_path: File path within the repository

        Returns:
            File content or None if not found
        """
        result = await self.db.execute(
            select(ParsedFile.content).where(
                and_(
                    ParsedFile.repository_id == repository_id,
                    ParsedFile.file_path == file_path,
                )
            )
        )
        row = result.first()
        return row[0] if row else None

    async def search_functions(
        self,
        repository_id: str,
        function_name: str,
        exact_match: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search for functions by name across all files in a repository.

        Args:
            repository_id: ParsedRepository ID
            function_name: Function name to search for
            exact_match: If True, require exact name match

        Returns:
            List of matching functions with file info
        """
        # Get all files for the repository
        files = await self.get_by_repository(repository_id)

        results = []
        for file in files:
            if not file.functions:
                continue

            for func in file.functions:
                func_name = func.get("name", "")
                if exact_match:
                    matches = func_name == function_name
                else:
                    matches = function_name.lower() in func_name.lower()

                if matches:
                    results.append({
                        "file_path": file.file_path,
                        "language": file.language,
                        "function": func,
                    })

        return results

    async def search_classes(
        self,
        repository_id: str,
        class_name: str,
        exact_match: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search for classes by name across all files in a repository.

        Args:
            repository_id: ParsedRepository ID
            class_name: Class name to search for
            exact_match: If True, require exact name match

        Returns:
            List of matching classes with file info
        """
        files = await self.get_by_repository(repository_id)

        results = []
        for file in files:
            if not file.classes:
                continue

            for cls in file.classes:
                cls_name = cls.get("name", "")
                if exact_match:
                    matches = cls_name == class_name
                else:
                    matches = class_name.lower() in cls_name.lower()

                if matches:
                    results.append({
                        "file_path": file.file_path,
                        "language": file.language,
                        "class": cls,
                    })

        return results

    async def create_batch(
        self,
        repository_id: str,
        files_data: List[Dict[str, Any]],
    ) -> int:
        """
        Batch create parsed file records.

        Args:
            repository_id: ParsedRepository ID
            files_data: List of file data dictionaries

        Returns:
            Number of files created
        """
        created_count = 0

        for file_data in files_data:
            content = file_data.get("content")
            content_hash = None
            if content:
                content_hash = hashlib.sha256(content.encode()).hexdigest()

            parsed_file = ParsedFile(
                id=str(uuid.uuid4()),
                repository_id=repository_id,
                file_path=file_data["file_path"],
                language=file_data["language"],
                size_bytes=file_data.get("size_bytes", 0),
                line_count=file_data.get("line_count", 0),
                functions=file_data.get("functions", []),
                classes=file_data.get("classes", []),
                imports=file_data.get("imports", []),
                is_parsed=file_data.get("is_parsed", True),
                parse_error=file_data.get("parse_error"),
                content=content,
                content_hash=content_hash,
            )

            self.db.add(parsed_file)
            created_count += 1

        await self.db.flush()
        logger.info(f"Created {created_count} ParsedFile records for repository {repository_id}")

        return created_count

    async def get_repository_stats(self, repository_id: str) -> Dict[str, Any]:
        """
        Get statistics for a parsed repository.

        Args:
            repository_id: ParsedRepository ID

        Returns:
            Dictionary with statistics
        """
        # Count files by language
        result = await self.db.execute(
            select(
                ParsedFile.language,
                func.count(ParsedFile.id).label("count"),
            )
            .where(ParsedFile.repository_id == repository_id)
            .group_by(ParsedFile.language)
        )
        languages = {row[0]: row[1] for row in result.fetchall()}

        # Count total functions and classes
        files = await self.get_by_repository(repository_id)

        total_functions = 0
        total_classes = 0
        total_imports = 0

        for file in files:
            if file.functions:
                total_functions += len(file.functions)
            if file.classes:
                total_classes += len(file.classes)
            if file.imports:
                total_imports += len(file.imports)

        return {
            "total_files": len(files),
            "languages": languages,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "total_imports": total_imports,
        }
