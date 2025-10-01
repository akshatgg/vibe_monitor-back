# Central API router include file
from fastapi import APIRouter

# Import domain routers
from app.onboarding.routes.router import router as auth_router
from app.onboarding.routes.workspace_router import router as workspace_router

from app.slack.router import slack_router

# from app.ingestion.router import router as ingestion_router
# from app.observability.router import router as observability_router
# from app.incidents.router import router as incidents_router
# from app.billing.router import router as billing_router

# Create main API router
api_router = APIRouter()

# Include domain routers with prefixes
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(workspace_router, tags=["workspaces"])
api_router.include_router(slack_router)
# api_router.include_router(ingestion_router, prefix="/ingestion", tags=["ingestion"])
# api_router.include_router(observability_router, prefix="/observability", tags=["observability"])
# api_router.include_router(incidents_router, prefix="/incidents", tags=["incidents"])
# api_router.include_router(billing_router, prefix="/billing", tags=["billing"])