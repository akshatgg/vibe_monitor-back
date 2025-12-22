"""
Datasources service layer for business logic
"""

import logging
from typing import Dict, List, Any

from sqlalchemy import select
import httpx

from app.core.database import AsyncSessionLocal
from app.models import GrafanaIntegration
from app.utils.retry_decorator import retry_external_api
from app.utils.token_processor import token_processor
from .models import LabelResponse

logger = logging.getLogger(__name__)


class DatasourcesService:
    """Service layer for datasources operations"""

    async def _get_workspace_config(self, workspace_id: str) -> tuple[str, str]:
        """Get Grafana config for a specific workspace from database"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GrafanaIntegration).where(
                    GrafanaIntegration.vm_workspace_id == workspace_id
                )
            )
            integration = result.scalar_one_or_none()

            if not integration:
                raise ValueError(
                    f"No Grafana configuration found for workspace {workspace_id}"
                )

            # Decrypt the API token before returning
            try:
                decrypted_token = token_processor.decrypt(integration.api_token)
                logger.debug("Successfully decrypted Grafana API token")
            except Exception as e:
                logger.error(f"Failed to decrypt Grafana API token: {e}")
                raise Exception("Failed to decrypt Grafana credentials")

            return integration.grafana_url, decrypted_token

    def _get_headers(self, api_token: str) -> Dict[str, str]:
        """Get headers for Grafana API requests"""
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        return headers

    async def get_datasources(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Get all datasources from Grafana"""
        try:
            base_url, api_token = await self._get_workspace_config(workspace_id)
            url = f"{base_url.rstrip('/')}/api/datasources"
            headers = self._get_headers(api_token)

            async with httpx.AsyncClient(timeout=10.0) as client:
                async for attempt in retry_external_api("Grafana"):
                    with attempt:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()
                        datasources = response.json()

                        # Return datasources with relevant fields
                        return [
                            {
                                "id": ds.get("id"),
                                "uid": ds.get("uid"),
                                "name": ds.get("name"),
                                "type": ds.get("type"),
                                "url": ds.get("url", ""),
                                "isDefault": ds.get("isDefault", False),
                            }
                            for ds in datasources
                        ]
        except Exception as e:
            logger.error(f"Failed to get datasources: {e}")
            raise

    async def get_labels(self, workspace_id: str, datasource_uid: str) -> LabelResponse:
        """Get all label keys for a specific datasource"""
        try:
            base_url, api_token = await self._get_workspace_config(workspace_id)

            # Get datasource type first to determine the correct API path
            datasource_info = await self._get_datasource_info(
                base_url, api_token, datasource_uid
            )
            datasource_type = datasource_info.get("type")

            # Construct the appropriate API path based on datasource type
            if datasource_type == "loki":
                api_path = "/loki/api/v1/labels"
            elif datasource_type == "prometheus":
                api_path = "/api/v1/labels"
            else:
                raise ValueError(f"Unsupported datasource type: {datasource_type}")

            url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}{api_path}"
            headers = self._get_headers(api_token)

            async with httpx.AsyncClient(timeout=30.0) as client:
                async for attempt in retry_external_api("Grafana"):
                    with attempt:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()
                        response_data = response.json()

                        if response_data.get("status") == "success":
                            return LabelResponse(
                                status="success", data=response_data.get("data", [])
                            )
                        else:
                            logger.error(f"Failed to get labels: {response_data}")
                            return LabelResponse(status="error", data=[])

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error getting labels: {e.response.status_code} - {e.response.text}"
            )
            return LabelResponse(status="error", data=[])
        except Exception as e:
            logger.error(f"Error getting labels: {e}")
            raise

    async def get_label_values(
        self, workspace_id: str, datasource_uid: str, label_name: str
    ) -> LabelResponse:
        """Get all values for a specific label in a datasource"""
        try:
            base_url, api_token = await self._get_workspace_config(workspace_id)

            # Get datasource type first to determine the correct API path
            datasource_info = await self._get_datasource_info(
                base_url, api_token, datasource_uid
            )
            datasource_type = datasource_info.get("type")

            # Construct the appropriate API path based on datasource type
            if datasource_type == "loki":
                api_path = f"/loki/api/v1/label/{label_name}/values"
            elif datasource_type == "prometheus":
                api_path = f"/api/v1/label/{label_name}/values"
            else:
                raise ValueError(f"Unsupported datasource type: {datasource_type}")

            url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}{api_path}"
            headers = self._get_headers(api_token)

            async with httpx.AsyncClient(timeout=30.0) as client:
                async for attempt in retry_external_api("Grafana"):
                    with attempt:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()
                        response_data = response.json()

                        if response_data.get("status") == "success":
                            return LabelResponse(
                                status="success", data=response_data.get("data", [])
                            )
                        else:
                            logger.error(f"Failed to get label values: {response_data}")
                            return LabelResponse(status="error", data=[])

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error getting label values: {e.response.status_code} - {e.response.text}"
            )
            return LabelResponse(status="error", data=[])
        except Exception as e:
            logger.error(f"Error getting label values: {e}")
            raise

    async def _get_datasource_info(
        self, base_url: str, api_token: str, datasource_uid: str
    ) -> Dict[str, Any]:
        """Get datasource information by UID"""
        url = f"{base_url.rstrip('/')}/api/datasources/uid/{datasource_uid}"
        headers = self._get_headers(api_token)

        async with httpx.AsyncClient(timeout=10.0) as client:
            async for attempt in retry_external_api("Grafana"):
                with attempt:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    return response.json()


# Global service instance
datasources_service = DatasourcesService()
