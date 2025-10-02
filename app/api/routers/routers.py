# Central API router include file
from fastapi import APIRouter

# Import domain routers
from app.onboarding.routes.router import router as auth_router
from app.onboarding.routes.workspace_router import router as workspace_router

from app.slack.router import slack_router



# Create main API router
api_router = APIRouter()

# Include domain routers with prefixes
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(workspace_router, tags=["workspaces"])
api_router.include_router(slack_router)
