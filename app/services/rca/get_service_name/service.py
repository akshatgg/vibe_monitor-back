"""
Service name extraction from GitHub repositories
Standalone functions for discovering service names using deterministic heuristics
"""

import re
import logging
import uuid
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models import RepositoryService
from app.github.tools.router import (
    get_repository_metadata,
    get_repository_tree,
    download_file_by_path,
)
from app.github.tools.service import get_github_integration_with_token

logger = logging.getLogger(__name__)


# Priority files to check based on language
LANGUAGE_FILES = {
    "Python": ["main.py", "app.py", "server.py", "__init__.py"],
    "JavaScript": ["index.js", "server.js", "app.js"],
    "TypeScript": ["index.ts", "server.ts", "app.ts"],
    "Go": ["main.go", "server.go"],
}

UNIVERSAL_FILES = ["Dockerfile", ".env", "package.json", "pyproject.toml"]

# Regex patterns for service name detection (ordered by priority)
SERVICE_PATTERNS = {
    # TOP PRIORITY: Dockerfile LABEL service.name="xxx"
    "dockerfile_label_service_name": r'LABEL\s+service\.name\s*=\s*["\']([a-zA-Z0-9_\-]+)["\']',

    # Other Dockerfile patterns
    "dockerfile_label_service": r'LABEL\s+service\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?',
    "dockerfile_env": r'ENV\s+(?:SERVICE_NAME|APP_NAME)\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?',

    # Application patterns
    "python_logger": r'logger\s*=\s*logging\.getLogger\(["\']([a-zA-Z0-9_\-\.]+)["\']\)',
    "fastapi_app": r'FastAPI\([^)]*title\s*=\s*["\']([^"\']+)["\']',
    "env_var": r'(?:SERVICE_NAME|APP_NAME)\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?',
    "package_name": r'"name"\s*:\s*"([a-zA-Z0-9_\-@/]+)"',
}


async def extract_service_names_from_repo(
    workspace_id: str,
    repo: str,
    user_id: str,
    db: AsyncSession
) -> List[str]:
    """
    Extract service names from a GitHub repository

    Args:
        workspace_id: Workspace ID
        repo: Repository name
        user_id: User ID for auth
        db: Database session

    Returns:
        List of discovered service names
    """
    try:
        print(f"\n🚀 Starting service name extraction for repo: {repo}")
        print(f"📦 Workspace ID: {workspace_id}")

        # Get GitHub integration and owner automatically from DB
        print(f"🔍 Fetching GitHub integration from database...")
        integration, _ = await get_github_integration_with_token(workspace_id, db)
        owner = integration.github_username
        print(f"✅ Found owner: {owner}")

        # Step 1: Get repository metadata for primary language
        print(f"\n📊 Step 1: Fetching repository metadata...")
        metadata = await get_repository_metadata(
            workspace_id=workspace_id,
            name=repo,
            owner=None,  # Let it use default from integration
            first=5,
            user_id=user_id,
            db=db
        )

        primary_language = _get_primary_language(metadata)
        print(f"🔤 Primary language detected: {primary_language or 'Unknown'}")
        logger.info(f"Primary language for {owner}/{repo}: {primary_language}")

        # Step 2: Get repository tree to list files
        print(f"\n🌳 Step 2: Fetching repository tree...")
        tree = await get_repository_tree(
            workspace_id=workspace_id,
            name=repo,
            owner=None,  # Let it use default from integration
            expression="HEAD:",
            user_id=user_id,
            db=db
        )

        files = _extract_file_names(tree)
        print(f"📁 Found {len(files)} files in repository")

        # Step 3: Prioritize files to analyze
        print(f"\n📋 Step 3: Prioritizing files for analysis...")
        priority_files = _get_priority_files(files, primary_language)
        print(f"🎯 Top priority files: {priority_files[:5]}")

        # Step 4: Check Dockerfile FIRST (top priority)
        print(f"\n🐳 Step 4: Checking Dockerfile for service.name label...")
        dockerfile_service = await _check_dockerfile_first(
            workspace_id=workspace_id,
            repo=repo,
            user_id=user_id,
            db=db,
            files=files
        )

        # If Dockerfile has service.name label, return immediately
        if dockerfile_service:
            print(f"🎉 Found service.name in Dockerfile: {dockerfile_service}")
            logger.info(f"Found service in Dockerfile: {dockerfile_service}")
            return [dockerfile_service]
        else:
            print(f"⚠️  No service.name label found in Dockerfile")

        # Step 5: Check other files if Dockerfile didn't have the label
        print(f"\n📝 Step 5: Analyzing other files for service names...")
        service_names = []
        for file_path in priority_files[:10]:  # Limit to 10 files
            # Skip Dockerfile since we already checked it
            if file_path.lower().startswith("dockerfile"):
                continue

            try:
                print(f"   🔎 Analyzing: {file_path}")
                file_content = await download_file_by_path(
                    workspace_id=workspace_id,
                    repo=repo,
                    file_path=file_path,
                    owner=None,  # Let it use default from integration
                    ref=None,
                    user_id=user_id,
                    db=db
                )

                if file_content.get("success") and file_content.get("content"):
                    names = _extract_service_names_from_content(file_content["content"])
                    if names:
                        print(f"   ✅ Found service names in {file_path}: {names}")
                        service_names.extend(names)
                    else:
                        print(f"   ⚪ No service names found in {file_path}")

            except Exception as e:
                print(f"   ❌ Failed to analyze {file_path}: {e}")
                logger.warning(f"Failed to analyze {file_path}: {e}")
                continue

        # Step 6: Return unique service names or fallback to repo name
        print(f"\n🔄 Step 6: Deduplicating and finalizing...")
        unique_names = list(set(service_names))
        if not unique_names:
            fallback_name = _normalize_name(repo)
            print(f"⚠️  No service names found, using fallback: {fallback_name}")
            unique_names = [fallback_name]
        else:
            print(f"✅ Final service names: {unique_names}")

        print(f"🏁 Service extraction complete!\n")
        return unique_names

    except Exception as e:
        print(f"\n❌ ERROR during service extraction: {e}")
        logger.error(f"Error extracting service names from {repo}: {e}")
        fallback = _normalize_name(repo)
        print(f"🔄 Returning fallback: {fallback}\n")
        return [fallback]


async def save_repository_services(
    workspace_id: str,
    repo_name: str,
    services: List[str],
    db: AsyncSession
) -> RepositoryService:
    """
    Save or update repository services in database

    Args:
        workspace_id: Workspace ID
        repo_name: Full repository name (owner/repo)
        services: List of service names
        db: Database session

    Returns:
        RepositoryService object
    """
    # Check if entry exists
    query = select(RepositoryService).where(
        and_(
            RepositoryService.workspace_id == workspace_id,
            RepositoryService.repo_name == repo_name
        )
    )
    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing
        existing.services = services
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        # Create new
        new_service = RepositoryService(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            repo_name=repo_name,
            services=services
        )
        db.add(new_service)
        await db.commit()
        await db.refresh(new_service)
        return new_service


async def get_repository_services(
    workspace_id: str,
    repo_name: Optional[str],
    db: AsyncSession
) -> List[RepositoryService]:
    """
    Get repository services from database

    Args:
        workspace_id: Workspace ID
        repo_name: Optional filter by repository name
        db: Database session

    Returns:
        List of RepositoryService objects
    """
    query = select(RepositoryService).where(
        RepositoryService.workspace_id == workspace_id
    )

    if repo_name:
        query = query.where(RepositoryService.repo_name == repo_name)

    query = query.order_by(RepositoryService.updated_at.desc())

    result = await db.execute(query)
    return result.scalars().all()


# Helper functions
def _get_primary_language(metadata: dict) -> Optional[str]:
    """Extract primary language from metadata"""
    try:
        edges = metadata.get("languages", {}).get("edges", [])
        if edges:
            return edges[0].get("node", {}).get("name")
    except:
        pass
    return None


def _extract_file_names(tree: dict) -> List[str]:
    """Extract file names from repository tree"""
    try:
        entries = tree.get("data", {}).get("entries", [])
        return [e.get("name") for e in entries if e.get("type") == "blob"]
    except:
        return []


def _get_priority_files(files: List[str], language: Optional[str]) -> List[str]:
    """Get prioritized list of files to analyze"""
    priority = []

    # Add language-specific files
    if language and language in LANGUAGE_FILES:
        for f in LANGUAGE_FILES[language]:
            if f in files:
                priority.append(f)

    # Add universal files
    for f in UNIVERSAL_FILES:
        if f in files and f not in priority:
            priority.append(f)

    # Add remaining files
    for f in files:
        if f not in priority:
            priority.append(f)

    return priority


def _extract_service_names_from_content(content: str) -> List[str]:
    """Extract service names from file content using regex"""
    names = []

    for pattern_name, pattern in SERVICE_PATTERNS.items():
        matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = next((m for m in match if m), None)
            if match:
                normalized = _normalize_name(match)
                if _is_valid_name(normalized):
                    print(f"      🔹 Pattern '{pattern_name}' matched: '{match}' → normalized: '{normalized}'")
                    names.append(normalized)

    return names


def _normalize_name(name: str) -> str:
    """Normalize service name"""
    # Remove common prefixes/suffixes
    name = re.sub(r'^(app-|service-|api-|@[^/]+/)', '', name)
    name = re.sub(r'(-app|-service|-api)$', '', name)

    # Convert to lowercase, replace special chars
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    return name.strip('-')


def _is_valid_name(name: str) -> bool:
    """Check if service name is valid"""
    if not name or len(name) < 2:
        return False

    # Skip generic names
    generic = {"app", "main", "index", "server", "service", "api", "test", "config"}
    if name in generic:
        return False

    return True


async def _check_dockerfile_first(
    workspace_id: str,
    repo: str,
    user_id: str,
    db: AsyncSession,
    files: List[str]
) -> Optional[str]:
    """
    Check Dockerfile for LABEL service.name="xxx" pattern (TOP PRIORITY)

    Returns:
        Service name if found in Dockerfile, None otherwise
    """
    # Find Dockerfile
    print(f"   🔍 Searching for Dockerfile in {len(files)} files...")
    dockerfile = None
    for f in files:
        if f.lower() in ["dockerfile", "dockerfile.prod", "dockerfile.dev"]:
            dockerfile = f
            break

    if not dockerfile:
        print(f"   ⚠️  No Dockerfile found in repository")
        logger.info("No Dockerfile found")
        return None

    try:
        # Download Dockerfile
        print(f"   📥 Downloading Dockerfile: {dockerfile}")
        logger.info(f"Checking Dockerfile: {dockerfile}")
        file_content = await download_file_by_path(
            workspace_id=workspace_id,
            repo=repo,
            file_path=dockerfile,
            owner=None,  # Let it use default from integration
            ref=None,
            user_id=user_id,
            db=db
        )

        if not file_content.get("success") or not file_content.get("content"):
            print(f"   ❌ Failed to download or empty Dockerfile")
            return None

        content = file_content["content"]
        print(f"   ✅ Dockerfile downloaded ({len(content)} bytes)")

        # Look for LABEL service.name="xxx" pattern
        print(f"   🔎 Searching for 'LABEL service.name' pattern...")
        pattern = r'LABEL\s+service\.name\s*=\s*["\']([a-zA-Z0-9_\-]+)["\']'
        match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)

        if match:
            service_name = match.group(1)
            print(f"   🎯 Found LABEL service.name: {service_name}")
            logger.info(f"Found LABEL service.name in Dockerfile: {service_name}")
            return service_name

        print(f"   ⚪ No 'LABEL service.name' found in Dockerfile")
        logger.info("Dockerfile exists but no service.name label found")
        return None

    except Exception as e:
        print(f"   ❌ Exception while checking Dockerfile: {e}")
        logger.warning(f"Failed to check Dockerfile: {e}")
        return None
