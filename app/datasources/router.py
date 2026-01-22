"""
FastAPI router for datasources endpoints
"""

import logging
from typing import List

from fastapi import APIRouter, Header, HTTPException

from ..core.config import settings
from .models import DatasourceResponse, LabelResponse
from .service import datasources_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasources", tags=["datasources"])


# ==================== STANDALONE FUNCTIONS ====================
# These functions can be called directly without FastAPI dependencies
# =========================================================


async def get_datasources_func(workspace_id: str) -> List[DatasourceResponse]:
    """Get list of all available Grafana datasources - Standalone function"""
    return await datasources_service.get_datasources(workspace_id)


async def get_datasource_labels_func(
    workspace_id: str, datasource_uid: str
) -> LabelResponse:
    """Get all label keys for a specific datasource - Standalone function"""
    return await datasources_service.get_labels(workspace_id, datasource_uid)


async def get_datasource_label_values_func(
    workspace_id: str, datasource_uid: str, label_name: str
) -> LabelResponse:
    """Get all values for a specific label in a datasource - Standalone function"""
    return await datasources_service.get_label_values(
        workspace_id, datasource_uid, label_name
    )


# ==================== FASTAPI ROUTER WRAPPER FUNCTIONS ====================
# These wrap the standalone functions with FastAPI dependencies
# =======================================================================


async def get_datasources_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
) -> List[DatasourceResponse]:
    """Get list of all available Grafana datasources - FastAPI endpoint"""
    try:
        return await get_datasources_func(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get datasources: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve datasources")


async def get_datasource_labels_endpoint(
    datasource_uid: str, workspace_id: str = Header(..., alias="workspace-id")
) -> LabelResponse:
    """Get all label keys for a specific datasource - FastAPI endpoint"""
    try:
        return await get_datasource_labels_func(workspace_id, datasource_uid)
    except ValueError as e:
        logger.error(f"Datasource error: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get labels for datasource {datasource_uid}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve datasource labels"
        )


async def get_datasource_label_values_endpoint(
    datasource_uid: str,
    label_name: str,
    workspace_id: str = Header(..., alias="workspace-id"),
) -> LabelResponse:
    """Get all values for a specific label in a datasource - FastAPI endpoint"""
    try:
        return await get_datasource_label_values_func(
            workspace_id, datasource_uid, label_name
        )
    except ValueError as e:
        logger.error(f"Datasource error: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get label values for datasource {datasource_uid}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve label values")


# ==================== CONDITIONAL ROUTE REGISTRATION ====================
# Register routes only in local development
# In deployed envs (dev/prod), standalone functions remain available for LLM usage
# =======================================================================

if settings.is_local:
    logger.info(f"ENVIRONMENT={settings.ENVIRONMENT}: Registering datasources routes")

    router.add_api_route(
        "",
        get_datasources_endpoint,
        methods=["GET"],
        response_model=List[DatasourceResponse],
    )

    router.add_api_route(
        "/{datasource_uid}/labels",
        get_datasource_labels_endpoint,
        methods=["GET"],
        response_model=LabelResponse,
    )

    router.add_api_route(
        "/{datasource_uid}/labels/{label_name}/values",
        get_datasource_label_values_endpoint,
        methods=["GET"],
        response_model=LabelResponse,
    )
else:
    logger.info(
        f"ENVIRONMENT={settings.ENVIRONMENT}: Datasources routes disabled (functions available for LLM usage)"
    )
