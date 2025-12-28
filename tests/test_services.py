"""
Test suite for Service management (billing domain).
Tests CRUD operations, authorization, and service limits.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

from app.billing.schemas import (
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceListResponse,
    ServiceCountResponse,
    FREE_TIER_SERVICE_LIMIT,
)
from app.billing.services.service_service import ServiceService
from app.models import Service, Workspace, Membership, Role


@pytest.fixture
def service_service():
    """Create a ServiceService instance."""
    return ServiceService()


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_workspace():
    """Create a sample workspace."""
    workspace = MagicMock(spec=Workspace)
    workspace.id = str(uuid.uuid4())
    workspace.name = "Test Workspace"
    workspace.is_paid = False
    return workspace


@pytest.fixture
def sample_membership():
    """Create a sample membership."""
    membership = MagicMock(spec=Membership)
    membership.id = str(uuid.uuid4())
    membership.user_id = str(uuid.uuid4())
    membership.workspace_id = str(uuid.uuid4())
    membership.role = Role.OWNER
    return membership


@pytest.fixture
def sample_service():
    """Create a sample service."""
    service = MagicMock(spec=Service)
    service.id = str(uuid.uuid4())
    service.workspace_id = str(uuid.uuid4())
    service.name = "api-gateway"
    service.repository_id = None
    service.repository_name = None
    service.enabled = True
    service.created_at = None
    service.updated_at = None
    return service


class TestServiceServiceOwnerVerification:
    """Tests for owner verification logic."""

    @pytest.mark.asyncio
    async def test_verify_owner_success(
        self, service_service, mock_db, sample_membership
    ):
        """Owner verification should succeed for workspace owners."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        membership = await service_service._verify_owner(
            sample_membership.workspace_id, sample_membership.user_id, mock_db
        )

        assert membership == sample_membership

    @pytest.mark.asyncio
    async def test_verify_owner_not_owner(self, service_service, mock_db):
        """Owner verification should fail for non-owners."""
        from fastapi import HTTPException

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await service_service._verify_owner("workspace-1", "user-1", mock_db)

        assert exc_info.value.status_code == 403
        assert "Only workspace owners" in exc_info.value.detail


class TestServiceServiceMemberVerification:
    """Tests for member verification logic."""

    @pytest.mark.asyncio
    async def test_verify_member_success(
        self, service_service, mock_db, sample_membership
    ):
        """Member verification should succeed for workspace members."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        membership = await service_service._verify_member(
            sample_membership.workspace_id, sample_membership.user_id, mock_db
        )

        assert membership == sample_membership

    @pytest.mark.asyncio
    async def test_verify_member_not_member(self, service_service, mock_db):
        """Member verification should fail for non-members."""
        from fastapi import HTTPException

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await service_service._verify_member("workspace-1", "user-1", mock_db)

        assert exc_info.value.status_code == 403
        assert "not a member" in exc_info.value.detail


class TestServiceServiceCount:
    """Tests for service count and limit logic."""

    @pytest.mark.asyncio
    async def test_get_service_count_free_tier(
        self, service_service, mock_db, sample_workspace
    ):
        """Service count should work for free tier workspaces."""
        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 3

        # Mock workspace query
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        mock_db.execute.side_effect = [count_result, workspace_result]

        result = await service_service.get_service_count(sample_workspace.id, mock_db)

        assert result.current_count == 3
        assert result.limit == FREE_TIER_SERVICE_LIMIT
        assert result.can_add_more is True
        assert result.is_paid is False

    @pytest.mark.asyncio
    async def test_get_service_count_at_limit(
        self, service_service, mock_db, sample_workspace
    ):
        """Should indicate limit reached when at max services."""
        count_result = MagicMock()
        count_result.scalar.return_value = FREE_TIER_SERVICE_LIMIT

        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        mock_db.execute.side_effect = [count_result, workspace_result]

        result = await service_service.get_service_count(sample_workspace.id, mock_db)

        assert result.current_count == FREE_TIER_SERVICE_LIMIT
        assert result.can_add_more is False

    @pytest.mark.asyncio
    async def test_validate_service_limit(
        self, service_service, mock_db, sample_workspace
    ):
        """Validate service limit should return correct tuple."""
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        mock_db.execute.side_effect = [count_result, workspace_result]

        can_add, current, limit = await service_service.validate_service_limit(
            sample_workspace.id, mock_db
        )

        assert can_add is True
        assert current == 2
        assert limit == FREE_TIER_SERVICE_LIMIT


class TestServiceServiceCreate:
    """Tests for service creation."""

    @pytest.mark.asyncio
    async def test_create_service_success(
        self, service_service, mock_db, sample_membership, sample_workspace
    ):
        """Should successfully create a service."""
        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock limit check (count + workspace)
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        # Mock uniqueness check
        unique_result = MagicMock()
        unique_result.scalar_one_or_none.return_value = None

        # Mock GitHub query
        github_result = MagicMock()
        github_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            owner_result,
            count_result,
            workspace_result,
            unique_result,
            github_result,
        ]

        # Create service
        service_data = ServiceCreate(name="api-gateway", repository_name="org/repo")

        result = await service_service.create_service(
            workspace_id=sample_workspace.id,
            service_data=service_data,
            user_id=sample_membership.user_id,
            db=mock_db,
        )

        assert result.name == "api-gateway"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_service_limit_exceeded(
        self, service_service, mock_db, sample_membership, sample_workspace
    ):
        """Should fail when service limit is exceeded."""
        from fastapi import HTTPException

        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock limit check - at limit
        count_result = MagicMock()
        count_result.scalar.return_value = FREE_TIER_SERVICE_LIMIT

        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        mock_db.execute.side_effect = [owner_result, count_result, workspace_result]

        service_data = ServiceCreate(name="api-gateway")

        with pytest.raises(HTTPException) as exc_info:
            await service_service.create_service(
                workspace_id=sample_workspace.id,
                service_data=service_data,
                user_id=sample_membership.user_id,
                db=mock_db,
            )

        assert exc_info.value.status_code == 400
        assert "limit reached" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_service_duplicate_name(
        self,
        service_service,
        mock_db,
        sample_membership,
        sample_workspace,
        sample_service,
    ):
        """Should fail when service name already exists in workspace."""
        from fastapi import HTTPException

        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock limit check
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        # Mock uniqueness check - service exists
        unique_result = MagicMock()
        unique_result.scalar_one_or_none.return_value = sample_service

        mock_db.execute.side_effect = [
            owner_result,
            count_result,
            workspace_result,
            unique_result,
        ]

        service_data = ServiceCreate(name="api-gateway")

        with pytest.raises(HTTPException) as exc_info:
            await service_service.create_service(
                workspace_id=sample_workspace.id,
                service_data=service_data,
                user_id=sample_membership.user_id,
                db=mock_db,
            )

        assert exc_info.value.status_code == 400
        assert "already exists" in exc_info.value.detail


class TestServiceServiceList:
    """Tests for listing services."""

    @pytest.mark.asyncio
    async def test_list_services_success(
        self,
        service_service,
        mock_db,
        sample_membership,
        sample_workspace,
        sample_service,
    ):
        """Should successfully list services in a workspace."""
        # Mock member verification
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = sample_membership

        # Mock services query
        services_result = MagicMock()
        services_result.scalars.return_value.all.return_value = [sample_service]

        # Mock limit check
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace

        mock_db.execute.side_effect = [member_result, services_result, workspace_result]

        result = await service_service.list_services(
            workspace_id=sample_workspace.id,
            user_id=sample_membership.user_id,
            db=mock_db,
        )

        assert result.total_count == 1
        assert len(result.services) == 1
        assert result.limit_reached is False


class TestServiceServiceGet:
    """Tests for getting a single service."""

    @pytest.mark.asyncio
    async def test_get_service_success(
        self, service_service, mock_db, sample_membership, sample_service
    ):
        """Should successfully get a service by ID."""
        # Mock member verification
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = sample_membership

        # Mock service query
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = sample_service

        mock_db.execute.side_effect = [member_result, service_result]

        result = await service_service.get_service(
            workspace_id=sample_service.workspace_id,
            service_id=sample_service.id,
            user_id=sample_membership.user_id,
            db=mock_db,
        )

        assert result.id == sample_service.id
        assert result.name == sample_service.name

    @pytest.mark.asyncio
    async def test_get_service_not_found(
        self, service_service, mock_db, sample_membership
    ):
        """Should raise 404 when service not found."""
        from fastapi import HTTPException

        # Mock member verification
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = sample_membership

        # Mock service query - not found
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [member_result, service_result]

        with pytest.raises(HTTPException) as exc_info:
            await service_service.get_service(
                workspace_id="workspace-1",
                service_id="nonexistent",
                user_id=sample_membership.user_id,
                db=mock_db,
            )

        assert exc_info.value.status_code == 404


class TestServiceServiceUpdate:
    """Tests for updating services."""

    @pytest.mark.asyncio
    async def test_update_service_name(
        self, service_service, mock_db, sample_membership, sample_service
    ):
        """Should successfully update service name."""
        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock service query
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = sample_service

        # Mock uniqueness check
        unique_result = MagicMock()
        unique_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [owner_result, service_result, unique_result]

        update_data = ServiceUpdate(name="new-api-gateway")

        await service_service.update_service(
            workspace_id=sample_service.workspace_id,
            service_id=sample_service.id,
            service_data=update_data,
            user_id=sample_membership.user_id,
            db=mock_db,
        )

        assert sample_service.name == "new-api-gateway"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_service_enabled(
        self, service_service, mock_db, sample_membership, sample_service
    ):
        """Should successfully update service enabled status."""
        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock service query
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = sample_service

        mock_db.execute.side_effect = [owner_result, service_result]

        update_data = ServiceUpdate(enabled=False)

        await service_service.update_service(
            workspace_id=sample_service.workspace_id,
            service_id=sample_service.id,
            service_data=update_data,
            user_id=sample_membership.user_id,
            db=mock_db,
        )

        assert sample_service.enabled is False


class TestServiceServiceDelete:
    """Tests for deleting services."""

    @pytest.mark.asyncio
    async def test_delete_service_success(
        self, service_service, mock_db, sample_membership, sample_service
    ):
        """Should successfully delete a service."""
        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock service query
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = sample_service

        mock_db.execute.side_effect = [owner_result, service_result]

        result = await service_service.delete_service(
            workspace_id=sample_service.workspace_id,
            service_id=sample_service.id,
            user_id=sample_membership.user_id,
            db=mock_db,
        )

        assert result is True
        mock_db.delete.assert_called_once_with(sample_service)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_service_not_found(
        self, service_service, mock_db, sample_membership
    ):
        """Should raise 404 when service not found."""
        from fastapi import HTTPException

        # Mock owner verification
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = sample_membership

        # Mock service query - not found
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [owner_result, service_result]

        with pytest.raises(HTTPException) as exc_info:
            await service_service.delete_service(
                workspace_id="workspace-1",
                service_id="nonexistent",
                user_id=sample_membership.user_id,
                db=mock_db,
            )

        assert exc_info.value.status_code == 404


class TestSchemas:
    """Tests for Pydantic schemas."""

    def test_service_create_valid(self):
        """ServiceCreate should accept valid data."""
        schema = ServiceCreate(name="api-gateway", repository_name="org/repo")
        assert schema.name == "api-gateway"
        assert schema.repository_name == "org/repo"

    def test_service_create_name_required(self):
        """ServiceCreate should require name."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceCreate()

    def test_service_create_name_min_length(self):
        """ServiceCreate name should have min length."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceCreate(name="")

    def test_service_update_all_optional(self):
        """ServiceUpdate should have all optional fields."""
        schema = ServiceUpdate()
        assert schema.name is None
        assert schema.repository_name is None
        assert schema.enabled is None

    def test_service_response_from_model(self):
        """ServiceResponse should be creatable from model attributes."""
        response = ServiceResponse(
            id="test-id",
            workspace_id="workspace-id",
            name="api-gateway",
            enabled=True,
        )
        assert response.id == "test-id"
        assert response.name == "api-gateway"

    def test_service_list_response(self):
        """ServiceListResponse should include metadata."""
        response = ServiceListResponse(
            services=[],
            total_count=0,
            limit=FREE_TIER_SERVICE_LIMIT,
            limit_reached=False,
        )
        assert response.total_count == 0
        assert response.limit == 5
        assert response.limit_reached is False

    def test_service_count_response(self):
        """ServiceCountResponse should include limit info."""
        response = ServiceCountResponse(
            current_count=3,
            limit=5,
            can_add_more=True,
            is_paid=False,
        )
        assert response.current_count == 3
        assert response.can_add_more is True
