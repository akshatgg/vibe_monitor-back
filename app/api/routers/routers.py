# Central API router include file
from fastapi import APIRouter

# Import domain routers
from app.onboarding.routes.router import router as auth_router
from app.onboarding.routes.workspace_router import router as workspace_router
from app.slack.router import slack_router

from app.log.router import router as log_router
from app.metrics.router import router as metrics_router
from app.datasources.router import router as datasources_router

from app.github.oauth.router import router as github_app_router

# Dev-only routers
from app.github.tools.router import router as github_tools_router
from app.github.webhook.router import router as github_webhook_router
from app.services.rca.get_service_name.router import router as get_servicename

# Config
from app.core.config import settings

from app.grafana.router import router as grafana_router

from app.mailgun.router import router as mailgun_router

from app.aws.Integration.router import router as aws_router
from app.aws.cloudwatch.Logs.router import router as cloudwatch_logs_router
from app.aws.cloudwatch.Metrics.router import router as cloudwatch_metrics_router

from app.newrelic.integration.router import router as newrelic_router
from app.newrelic.Logs.router import router as newrelic_logs_router
from app.newrelic.Metrics.router import router as newrelic_metrics_router
from app.datadog.integration.router import router as datadog_router
from app.datadog.Logs.router import router as datadog_logs_router
from app.datadog.Metrics.router import router as datadog_metrics_router

# Create main API router
api_router = APIRouter()

# Include domain routers with prefixes
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(workspace_router, tags=["workspaces"])
api_router.include_router(slack_router)
api_router.include_router(log_router)
api_router.include_router(metrics_router)
api_router.include_router(datasources_router)
api_router.include_router(github_app_router, tags=["github-oauth"])

# Include dev-only routers (only exposed in local development)
if settings.is_local:
    api_router.include_router(github_tools_router, tags=["github-tools"])
    api_router.include_router(get_servicename, tags=["repository-services"])
api_router.include_router(github_webhook_router, tags=["github-webhooks"])
api_router.include_router(mailgun_router, tags=["mailgun"])
api_router.include_router(grafana_router, tags=["grafana"])
api_router.include_router(aws_router, tags=["aws-integration"])

api_router.include_router(newrelic_router, tags=["newrelic-integration"])
api_router.include_router(datadog_router, tags=["datadog-integration"])


# CloudWatch/NewRelic/Datadog routers only in local (for testing via Postman/Swagger)
# In deployed envs (dev/prod), RCA bot accesses service functions directly (no HTTP routes)
if settings.is_local:
    api_router.include_router(cloudwatch_logs_router, tags=["cloudwatch-logs"])
    api_router.include_router(cloudwatch_metrics_router, tags=["cloudwatch-metrics"])
    api_router.include_router(newrelic_logs_router, tags=["newrelic-logs"])
    api_router.include_router(newrelic_metrics_router, tags=["newrelic-metrics"])
    api_router.include_router(datadog_logs_router, tags=["datadog-logs"])
    api_router.include_router(datadog_metrics_router, tags=["datadog-metrics"])
