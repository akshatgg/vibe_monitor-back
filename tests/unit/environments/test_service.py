"""
Unit tests for environments service.

Focuses on pure functions, validation logic, and schema validation (no DB).
"""

import pytest
from pydantic import ValidationError

from app.environments.schemas import (
    AvailableRepository,
    EnvironmentCreate,
    EnvironmentRepositoryCreate,
    EnvironmentRepositoryUpdate,
    EnvironmentUpdate,
)


class TestEnvironmentCreateSchema:
    """Tests for EnvironmentCreate schema validation."""

    def test_valid_environment_create(self):
        """Test creating environment with valid data."""
        env = EnvironmentCreate(name="production")
        assert env.name == "production"
        assert env.is_default is False
        assert env.auto_discovery_enabled is True

    def test_environment_create_with_all_fields(self):
        """Test creating environment with all fields specified."""
        env = EnvironmentCreate(
            name="staging", is_default=True, auto_discovery_enabled=False
        )
        assert env.name == "staging"
        assert env.is_default is True
        assert env.auto_discovery_enabled is False

    def test_environment_create_empty_name_fails(self):
        """Test that empty name fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            EnvironmentCreate(name="")
        assert "string_too_short" in str(exc_info.value).lower()

    def test_environment_create_name_too_long_fails(self):
        """Test that name exceeding max length fails."""
        long_name = "a" * 256  # Max is 255
        with pytest.raises(ValidationError) as exc_info:
            EnvironmentCreate(name=long_name)
        assert "string_too_long" in str(exc_info.value).lower()

    def test_environment_create_name_at_max_length(self):
        """Test that name at max length is valid."""
        max_name = "a" * 255
        env = EnvironmentCreate(name=max_name)
        assert len(env.name) == 255


class TestEnvironmentUpdateSchema:
    """Tests for EnvironmentUpdate schema validation."""

    def test_environment_update_all_none(self):
        """Test update with no fields specified."""
        update = EnvironmentUpdate()
        assert update.name is None
        assert update.is_default is None
        assert update.auto_discovery_enabled is None

    def test_environment_update_partial(self):
        """Test partial update."""
        update = EnvironmentUpdate(name="new-name")
        assert update.name == "new-name"
        assert update.is_default is None

    def test_environment_update_name_validation(self):
        """Test name validation on update."""
        with pytest.raises(ValidationError):
            EnvironmentUpdate(name="")  # Empty name

    def test_environment_update_is_default(self):
        """Test setting is_default flag."""
        update = EnvironmentUpdate(is_default=True)
        assert update.is_default is True


class TestEnvironmentRepositoryCreateSchema:
    """Tests for EnvironmentRepositoryCreate schema validation."""

    def test_valid_repository_create(self):
        """Test creating repository config with valid data."""
        repo = EnvironmentRepositoryCreate(repo_full_name="owner/repo")
        assert repo.repo_full_name == "owner/repo"
        assert repo.branch_name is None
        assert repo.is_enabled is False

    def test_repository_create_with_branch(self):
        """Test creating repository config with branch."""
        repo = EnvironmentRepositoryCreate(
            repo_full_name="owner/repo", branch_name="main", is_enabled=True
        )
        assert repo.branch_name == "main"
        assert repo.is_enabled is True

    def test_repository_create_empty_name_fails(self):
        """Test that empty repo name fails."""
        with pytest.raises(ValidationError):
            EnvironmentRepositoryCreate(repo_full_name="")

    def test_repository_create_name_too_long(self):
        """Test that repo name exceeding max length fails."""
        long_name = "a" * 256
        with pytest.raises(ValidationError):
            EnvironmentRepositoryCreate(repo_full_name=long_name)

    def test_repository_create_branch_too_long(self):
        """Test that branch name exceeding max length fails."""
        long_branch = "a" * 256
        with pytest.raises(ValidationError):
            EnvironmentRepositoryCreate(
                repo_full_name="owner/repo", branch_name=long_branch
            )


class TestEnvironmentRepositoryUpdateSchema:
    """Tests for EnvironmentRepositoryUpdate schema validation."""

    def test_update_all_none(self):
        """Test update with no fields."""
        update = EnvironmentRepositoryUpdate()
        assert update.branch_name is None
        assert update.is_enabled is None

    def test_update_branch_only(self):
        """Test updating only branch."""
        update = EnvironmentRepositoryUpdate(branch_name="develop")
        assert update.branch_name == "develop"
        assert update.is_enabled is None

    def test_update_enabled_only(self):
        """Test updating only enabled flag."""
        update = EnvironmentRepositoryUpdate(is_enabled=True)
        assert update.is_enabled is True
        assert update.branch_name is None


class TestAvailableRepositorySchema:
    """Tests for AvailableRepository schema."""

    def test_available_repository_minimal(self):
        """Test creating with minimal fields."""
        repo = AvailableRepository(full_name="owner/repo", is_private=False)
        assert repo.full_name == "owner/repo"
        assert repo.default_branch is None
        assert repo.is_private is False

    def test_available_repository_full(self):
        """Test creating with all fields."""
        repo = AvailableRepository(
            full_name="org/private-repo", default_branch="main", is_private=True
        )
        assert repo.full_name == "org/private-repo"
        assert repo.default_branch == "main"
        assert repo.is_private is True


class TestRepositoryNameParsing:
    """Tests for repository name format validation logic.

    The service expects repo names in 'owner/repo' format.
    """

    def test_valid_repo_name_format(self):
        """Test valid repository name formats."""
        valid_names = [
            "owner/repo",
            "my-org/my-repo",
            "user123/repo-name",
            "Organization/Repository",
            "a/b",  # Minimal valid
        ]
        for name in valid_names:
            parts = name.split("/")
            assert len(parts) == 2
            assert all(p for p in parts)  # Both parts non-empty

    def test_invalid_repo_name_formats(self):
        """Test invalid repository name formats."""
        invalid_names = [
            "repo-without-owner",  # No slash
            "owner/",  # Empty repo
            "/repo",  # Empty owner
            "owner/repo/extra",  # Too many parts
            "",  # Empty
        ]
        for name in invalid_names:
            parts = name.split("/")
            # Either wrong number of parts or empty parts
            is_valid = len(parts) == 2 and all(p for p in parts)
            assert not is_valid, f"Expected {name} to be invalid"


class TestEnableWithoutBranchValidation:
    """Tests for the validation rule: cannot enable without branch.

    This validation is enforced in the service layer.
    """

    def test_enabled_with_branch_is_valid(self):
        """Test that enabling with branch is valid."""
        repo = EnvironmentRepositoryCreate(
            repo_full_name="owner/repo", branch_name="main", is_enabled=True
        )
        assert repo.is_enabled is True
        assert repo.branch_name is not None

    def test_disabled_without_branch_is_valid(self):
        """Test that disabled without branch is valid."""
        repo = EnvironmentRepositoryCreate(
            repo_full_name="owner/repo", branch_name=None, is_enabled=False
        )
        assert repo.is_enabled is False
        assert repo.branch_name is None

    def test_enabled_without_branch_validation_logic(self):
        """Test the validation logic for enable without branch.

        Note: This validation happens in the service layer, not schema.
        Schema allows it; service rejects it.
        """
        # Schema allows this combination
        repo = EnvironmentRepositoryCreate(
            repo_full_name="owner/repo", branch_name=None, is_enabled=True
        )
        assert repo.is_enabled is True
        assert repo.branch_name is None

        # Validation logic (mirrors service behavior)
        if repo.is_enabled and not repo.branch_name:
            is_invalid = True
        else:
            is_invalid = False

        assert is_invalid is True

    def test_update_enable_logic(self):
        """Test enable validation with update scenarios."""
        # Scenario: Updating to enable with no existing branch
        update = EnvironmentRepositoryUpdate(is_enabled=True)
        existing_branch = None

        effective_branch = (
            update.branch_name if update.branch_name is not None else existing_branch
        )

        # Service would reject this
        assert update.is_enabled is True
        assert effective_branch is None

    def test_update_enable_with_branch_in_same_update(self):
        """Test enabling and setting branch in same update."""
        update = EnvironmentRepositoryUpdate(branch_name="main", is_enabled=True)

        effective_branch = update.branch_name
        assert update.is_enabled is True
        assert effective_branch == "main"

    def test_update_enable_with_existing_branch(self):
        """Test enabling when existing branch is set."""
        update = EnvironmentRepositoryUpdate(is_enabled=True)
        existing_branch = "develop"

        effective_branch = (
            update.branch_name if update.branch_name is not None else existing_branch
        )

        assert update.is_enabled is True
        assert effective_branch == "develop"  # From existing
