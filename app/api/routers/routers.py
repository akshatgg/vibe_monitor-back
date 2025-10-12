# Central API router include file
from fastapi import APIRouter

# Import domain routers
from app.onboarding.routes.router import router as auth_router
from app.onboarding.routes.workspace_router import router as workspace_router
from app.log.router import router as log_router
from app.metrics.router import router as metrics_router
from app.slack.router import slack_router


from app.github.oauth.router import router as github_app_router
from app.github.tools.router import router as github_tools_router


# Create main API router
api_router = APIRouter()

# Include domain routers with prefixes
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(workspace_router, tags=["workspaces"])
api_router.include_router(slack_router)
api_router.include_router(log_router, tags=["logs"])
api_router.include_router(metrics_router, tags=["metrics"])
api_router.include_router(github_app_router, tags=["github-oauth"])
api_router.include_router(github_tools_router)

