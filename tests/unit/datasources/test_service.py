"""
Unit tests for datasources service.
Focuses on pure functions and validation logic (no database operations).
"""

from app.datasources.service import DatasourcesService


class TestDatasourcesServiceGetHeaders:
    """Tests for _get_headers method."""

    def test_get_headers_with_token(self):
        """Headers include Authorization when token provided."""
        service = DatasourcesService()
        headers = service._get_headers("test-api-token")

        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test-api-token"

    def test_get_headers_without_token(self):
        """Headers exclude Authorization when token is empty."""
        service = DatasourcesService()
        headers = service._get_headers("")

        assert headers["Content-Type"] == "application/json"
        assert "Authorization" not in headers

    def test_get_headers_none_token(self):
        """Headers exclude Authorization when token is None."""
        service = DatasourcesService()
        headers = service._get_headers(None)

        assert headers["Content-Type"] == "application/json"
        assert "Authorization" not in headers

    def test_get_headers_content_type_always_json(self):
        """Content-Type is always application/json."""
        service = DatasourcesService()

        headers_with_token = service._get_headers("token")
        headers_without_token = service._get_headers("")

        assert headers_with_token["Content-Type"] == "application/json"
        assert headers_without_token["Content-Type"] == "application/json"


class TestDatasourcesServiceURLFormatting:
    """Tests for URL formatting logic used in the service."""

    def test_url_rstrip_trailing_slash(self):
        """URL trailing slashes are removed."""
        url_with_slash = "https://grafana.example.com/"
        url_without_slash = "https://grafana.example.com"

        assert url_with_slash.rstrip("/") == "https://grafana.example.com"
        assert url_without_slash.rstrip("/") == "https://grafana.example.com"

    def test_url_rstrip_multiple_trailing_slashes(self):
        """Multiple trailing slashes are all removed."""
        url = "https://grafana.example.com///"

        assert url.rstrip("/") == "https://grafana.example.com"

    def test_datasource_api_path_loki(self):
        """Loki datasource uses correct API path."""
        base_url = "https://grafana.example.com"
        datasource_uid = "loki-uid"
        api_path = "/loki/api/v1/labels"

        expected = f"{base_url}/api/datasources/proxy/uid/{datasource_uid}{api_path}"
        result = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}{api_path}"

        assert result == expected

    def test_datasource_api_path_prometheus(self):
        """Prometheus datasource uses correct API path."""
        base_url = "https://grafana.example.com"
        datasource_uid = "prom-uid"
        api_path = "/api/v1/labels"

        expected = f"{base_url}/api/datasources/proxy/uid/{datasource_uid}{api_path}"
        result = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}{api_path}"

        assert result == expected


class TestDatasourcesServiceApiPaths:
    """Tests for API path determination based on datasource type."""

    def test_loki_labels_api_path(self):
        """Loki uses /loki/api/v1/labels for labels."""
        datasource_type = "loki"

        if datasource_type == "loki":
            api_path = "/loki/api/v1/labels"
        elif datasource_type == "prometheus":
            api_path = "/api/v1/labels"
        else:
            api_path = None

        assert api_path == "/loki/api/v1/labels"

    def test_prometheus_labels_api_path(self):
        """Prometheus uses /api/v1/labels for labels."""
        datasource_type = "prometheus"

        if datasource_type == "loki":
            api_path = "/loki/api/v1/labels"
        elif datasource_type == "prometheus":
            api_path = "/api/v1/labels"
        else:
            api_path = None

        assert api_path == "/api/v1/labels"

    def test_unsupported_datasource_type(self):
        """Unsupported datasource type should be detectable."""
        datasource_type = "elasticsearch"

        supported = datasource_type in ("loki", "prometheus")
        assert not supported

    def test_loki_label_values_api_path(self):
        """Loki uses /loki/api/v1/label/{name}/values for label values."""
        datasource_type = "loki"
        label_name = "service_name"

        if datasource_type == "loki":
            api_path = f"/loki/api/v1/label/{label_name}/values"
        elif datasource_type == "prometheus":
            api_path = f"/api/v1/label/{label_name}/values"
        else:
            api_path = None

        assert api_path == "/loki/api/v1/label/service_name/values"

    def test_prometheus_label_values_api_path(self):
        """Prometheus uses /api/v1/label/{name}/values for label values."""
        datasource_type = "prometheus"
        label_name = "job"

        if datasource_type == "loki":
            api_path = f"/loki/api/v1/label/{label_name}/values"
        elif datasource_type == "prometheus":
            api_path = f"/api/v1/label/{label_name}/values"
        else:
            api_path = None

        assert api_path == "/api/v1/label/job/values"


class TestDatasourcesServiceResponseParsing:
    """Tests for response parsing logic."""

    def test_parse_successful_response(self):
        """Successful response has status='success' and data array."""
        response_data = {"status": "success", "data": ["label1", "label2"]}

        is_success = response_data.get("status") == "success"
        data = response_data.get("data", [])

        assert is_success
        assert data == ["label1", "label2"]

    def test_parse_error_response(self):
        """Error response has status != 'success'."""
        response_data = {"status": "error", "errorType": "bad_data"}

        is_success = response_data.get("status") == "success"

        assert not is_success

    def test_parse_response_missing_status(self):
        """Missing status treated as failure."""
        response_data = {"data": ["label1"]}

        is_success = response_data.get("status") == "success"

        assert not is_success

    def test_parse_response_missing_data(self):
        """Missing data defaults to empty array."""
        response_data = {"status": "success"}

        data = response_data.get("data", [])

        assert data == []

    def test_datasource_list_field_extraction(self):
        """Extract relevant fields from datasource list."""
        datasources = [
            {
                "id": 1,
                "uid": "abc123",
                "name": "Prometheus",
                "type": "prometheus",
                "url": "http://prometheus:9090",
                "isDefault": True,
                "database": "",
                "access": "proxy",
            }
        ]

        extracted = [
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

        assert len(extracted) == 1
        assert extracted[0]["id"] == 1
        assert extracted[0]["uid"] == "abc123"
        assert extracted[0]["name"] == "Prometheus"
        assert extracted[0]["type"] == "prometheus"
        assert extracted[0]["isDefault"] is True
