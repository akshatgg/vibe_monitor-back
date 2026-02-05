"""
Tests for RCA context formatting utility functions
"""

from unittest.mock import MagicMock

from app.services.rca.capabilities import ExecutionContext
from app.services.rca.context_utils import (
    build_context_string,
    format_deployed_commits_display,
    format_environments_display,
    format_integrations_display,
    format_service_mapping_display,
    format_thread_history_for_prompt,
    get_context_summary,
    get_default_environment,
    get_deployed_commits,
    get_environment_list,
    get_thread_history,
)


class TestFormatEnvironmentsDisplay:
    """Tests for format_environments_display function"""

    def test_formats_with_default_marker(self):
        """Should add (default) marker to default environment"""
        env_context = {
            "environments": [
                {"name": "test", "is_default": False},
                {"name": "test2", "is_default": True},
            ],
            "default_environment": "test2",
        }
        result = format_environments_display(env_context)
        assert result == "test, test2 (default)"

    def test_formats_single_environment_with_default(self):
        """Should handle single default environment"""
        env_context = {
            "environments": [{"name": "production", "is_default": True}],
            "default_environment": "production",
        }
        result = format_environments_display(env_context)
        assert result == "production (default)"

    def test_formats_without_default(self):
        """Should format environments when no default is set"""
        env_context = {
            "environments": [
                {"name": "dev", "is_default": False},
                {"name": "staging", "is_default": False},
            ],
            "default_environment": None,
        }
        result = format_environments_display(env_context)
        assert result == "dev, staging"

    def test_handles_empty_environments(self):
        """Should return empty string when no environments"""
        env_context = {"environments": [], "default_environment": None}
        result = format_environments_display(env_context)
        assert result == ""

    def test_handles_none_context(self):
        """Should return empty string when context is None"""
        result = format_environments_display(None)
        assert result == ""

    def test_handles_missing_environments_key(self):
        """Should return empty string when environments key missing"""
        env_context = {"default_environment": "prod"}
        result = format_environments_display(env_context)
        assert result == ""

    def test_ignores_non_dict_entries(self):
        """Should skip non-dict entries in environments list"""
        env_context = {
            "environments": [
                {"name": "prod", "is_default": True},
                "invalid_entry",  # Should be skipped
                {"name": "dev", "is_default": False},
            ],
            "default_environment": "prod",
        }
        result = format_environments_display(env_context)
        assert result == "prod (default), dev"

    def test_ignores_entries_without_name(self):
        """Should skip entries that don't have a name"""
        env_context = {
            "environments": [
                {"name": "prod", "is_default": True},
                {"is_default": False},  # No name - should be skipped
            ],
            "default_environment": "prod",
        }
        result = format_environments_display(env_context)
        assert result == "prod (default)"


class TestFormatServiceMappingDisplay:
    """Tests for format_service_mapping_display function"""

    def test_formats_single_service(self):
        """Should format single service→repo mapping"""
        mapping = {"marketplace-service": "marketplace"}
        result = format_service_mapping_display(mapping)
        assert result == "marketplace-service (repo: marketplace)"

    def test_formats_multiple_services(self):
        """Should format multiple service→repo mappings"""
        mapping = {
            "marketplace-service": "marketplace",
            "auth-service": "auth",
        }
        result = format_service_mapping_display(mapping)
        # Order might vary, so check both services are present
        assert "marketplace-service (repo: marketplace)" in result
        assert "auth-service (repo: auth)" in result
        assert ", " in result  # Check they're comma-separated

    def test_handles_empty_mapping(self):
        """Should return empty string when mapping is empty"""
        result = format_service_mapping_display({})
        assert result == ""

    def test_handles_none_mapping(self):
        """Should return empty string when mapping is None"""
        result = format_service_mapping_display(None)
        assert result == ""


class TestFormatIntegrationsDisplay:
    """Tests for format_integrations_display function"""

    def _make_integration(self, status="active", health_status="healthy"):
        """Helper to create mock integration objects"""
        integration = MagicMock()
        integration.status = status
        integration.health_status = health_status
        return integration

    def test_formats_configured_integrations(self):
        """Should format configured integrations with status and health"""
        integrations = {
            "github": self._make_integration(status="active", health_status="healthy"),
        }
        all_types = {"github", "aws", "datadog"}
        result = format_integrations_display(integrations, all_types)
        assert "Configured integrations: github (active, healthy)" in result
        assert "Not configured: aws, datadog" in result

    def test_formats_multiple_configured_integrations(self):
        """Should format multiple configured integrations alphabetically"""
        integrations = {
            "github": self._make_integration(status="active", health_status="healthy"),
            "aws": self._make_integration(status="active", health_status="healthy"),
        }
        all_types = {"github", "aws", "datadog"}
        result = format_integrations_display(integrations, all_types)
        assert "aws (active, healthy)" in result
        assert "github (active, healthy)" in result
        assert "Not configured: datadog" in result

    def test_handles_unhealthy_integrations(self):
        """Should show unhealthy status in display"""
        integrations = {
            "github": self._make_integration(status="active", health_status="failed"),
        }
        all_types = {"github", "aws"}
        result = format_integrations_display(integrations, all_types)
        assert "github (active, failed)" in result

    def test_handles_none_status_values(self):
        """Should default to 'active' for None status and 'unchecked' for None health"""
        integrations = {
            "github": self._make_integration(status=None, health_status=None),
        }
        all_types = {"github", "aws"}
        result = format_integrations_display(integrations, all_types)
        assert "github (active, unchecked)" in result

    def test_handles_all_configured(self):
        """Should only show configured section when all integrations are configured"""
        integrations = {
            "github": self._make_integration(),
            "aws": self._make_integration(),
        }
        all_types = {"github", "aws"}
        result = format_integrations_display(integrations, all_types)
        assert "Configured integrations:" in result
        assert "Not configured" not in result

    def test_handles_none_configured(self):
        """Should only show not configured section when no integrations are configured"""
        integrations = {}
        all_types = {"github", "aws", "datadog"}
        result = format_integrations_display(integrations, all_types)
        assert "Configured integrations" not in result
        assert "Not configured: aws, datadog, github" in result

    def test_handles_empty_integration_types(self):
        """Should return empty string when no integration types provided"""
        integrations = {"github": self._make_integration()}
        result = format_integrations_display(integrations, set())
        assert result == ""

    def test_handles_empty_both(self):
        """Should return empty string when both are empty"""
        result = format_integrations_display({}, set())
        assert result == ""

    def test_sorts_integration_names_alphabetically(self):
        """Should sort integration names alphabetically"""
        integrations = {}
        all_types = {"newrelic", "aws", "github", "datadog"}
        result = format_integrations_display(integrations, all_types)
        # Verify alphabetical order
        assert result == "Not configured: aws, datadog, github, newrelic"


class TestFormatDeployedCommitsDisplay:
    """Tests for format_deployed_commits_display function"""

    def test_formats_deployed_commits_for_default_env(self):
        """Should format deployed commits for default environment"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123def", "auth": "xyz789abc"}
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "prod: marketplace@abc123d, auth@xyz789a"

    def test_formats_deployed_commits_for_specific_env(self):
        """Should format deployed commits for specified environment"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"},
                        "dev": {"marketplace": "def456"},
                    },
                }
            }
        }
        result = format_deployed_commits_display(state, environment_name="dev")
        assert result == "dev: marketplace@def456"

    def test_returns_no_deployments_message_when_empty(self):
        """Should return no deployments message when commits dict is empty"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "test",
                    "deployed_commits_by_environment": {"test": {}},
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "test: No deployments configured"

    def test_returns_empty_when_no_environment(self):
        """Should return empty string when no environment is configured"""
        state = {"context": {"environment_context": {}}}
        result = format_deployed_commits_display(state)
        assert result == ""

    def test_returns_no_deployments_for_specific_env_when_empty(self):
        """Should return no deployments message for specific environment when empty"""
        state = {
            "context": {
                "environment_context": {
                    "deployed_commits_by_environment": {"staging": {}}
                }
            }
        }
        result = format_deployed_commits_display(state, environment_name="staging")
        assert result == "staging: No deployments configured"

    def test_truncates_commit_sha_to_7_chars(self):
        """Should truncate commit SHA to 7 characters"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123def456ghi789"}
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert "abc123d" in result
        assert "abc123def456" not in result

    def test_handles_multiple_repos_with_deployments(self):
        """Should handle multiple repositories with different commits"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {
                            "marketplace": "aaa1111",
                            "auth": "bbb2222",
                            "payment": "ccc3333",
                        }
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert "prod:" in result
        assert "marketplace@aaa1111" in result
        assert "auth@bbb2222" in result
        assert "payment@ccc3333" in result

    def test_handles_none_commit_values(self):
        """Should skip repos with None commit values"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123", "auth": None}
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "prod: marketplace@abc123"
        assert "auth" not in result

    def test_handles_all_none_commit_values(self):
        """Should return no deployments message when all commits are None"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": None, "auth": None}
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "prod: No deployments configured"

    def test_handles_non_string_commit_values(self):
        """Should skip repos with non-string commit values"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123", "auth": 12345}
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "prod: marketplace@abc123"
        assert "12345" not in result

    def test_handles_dict_format_from_worker(self):
        """Should handle dict format with commit_sha and deployed_at from worker.py"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {
                            "Vibe-Monitor/marketplace": {
                                "commit_sha": "ab2f9b1c73b71809ba273d68b0ad4312c500190c",
                                "deployed_at": "2026-02-04T14:49:00+00:00",
                            }
                        }
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "prod: Vibe-Monitor/marketplace@ab2f9b1"

    def test_handles_mixed_string_and_dict_formats(self):
        """Should handle mix of string and dict formats in same environment"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {
                            "marketplace": "abc123def",
                            "auth": {
                                "commit_sha": "xyz789abc",
                                "deployed_at": "2026-02-04T14:49:00+00:00",
                            },
                        }
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert "marketplace@abc123d" in result
        assert "auth@xyz789a" in result

    def test_handles_dict_format_with_none_commit_sha(self):
        """Should skip dict entries with None commit_sha"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {
                            "marketplace": {
                                "commit_sha": "abc123",
                                "deployed_at": "2026-02-04",
                            },
                            "auth": {"commit_sha": None, "deployed_at": "2026-02-04"},
                        }
                    },
                }
            }
        }
        result = format_deployed_commits_display(state)
        assert result == "prod: marketplace@abc123"
        assert "auth" not in result


class TestBuildContextString:
    """Tests for build_context_string function"""

    def test_builds_full_context_with_deployments(self):
        """Should build complete context with services, environments, and deployments"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={"marketplace-service": "marketplace"},
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [
                        {"name": "prod", "is_default": True},
                        {"name": "dev", "is_default": False},
                    ],
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"}
                    },
                }
            }
        }

        result = build_context_string(execution_context, state)

        assert "Available services: marketplace-service (repo: marketplace)" in result
        assert "Available environments: prod (default), dev" in result
        assert "Deployed commits: prod: marketplace@abc123" in result
        assert "; " in result  # Check semicolon separator

    def test_builds_services_only(self):
        """Should build context with only services when include_environments=False"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={"marketplace-service": "marketplace"},
        )
        state = {"context": {"environment_context": {}}}

        result = build_context_string(
            execution_context, state, include_environments=False
        )

        assert "marketplace-service (repo: marketplace)" in result
        assert "Available environments" not in result

    def test_builds_environments_only(self):
        """Should build context with only environments when include_services=False"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={},
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [{"name": "prod", "is_default": True}],
                    "default_environment": "prod",
                }
            }
        }

        result = build_context_string(execution_context, state, include_services=False)

        assert "Available environments: prod (default)" in result
        assert "Available services" not in result

    def test_builds_deployments_only(self):
        """Should build context with only deployed commits when include_services=False and include_environments=False"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={},
        )
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"}
                    },
                }
            }
        }

        result = build_context_string(
            execution_context, state, include_services=False, include_environments=False
        )

        assert "Deployed commits: prod: marketplace@abc123" in result
        assert "Available services" not in result
        assert "Available environments" not in result

    def test_excludes_deployments_when_flag_false(self):
        """Should not include deployed commits when include_deployed_commits=False"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={"marketplace-service": "marketplace"},
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [{"name": "prod", "is_default": True}],
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"}
                    },
                }
            }
        }

        result = build_context_string(
            execution_context, state, include_deployed_commits=False
        )

        assert "Available services: marketplace-service (repo: marketplace)" in result
        assert "Available environments: prod (default)" in result
        assert "Deployed commits" not in result

    def test_handles_empty_context(self):
        """Should return empty string when no context available"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={},
        )
        state = {}

        result = build_context_string(
            execution_context, state, include_integrations=False
        )
        assert result == ""

    def test_includes_integrations_by_default(self):
        """Should include integration status by default"""

        def _make_integration(status="active", health_status="healthy"):
            integration = MagicMock()
            integration.status = status
            integration.health_status = health_status
            return integration

        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={
                "github": _make_integration(status="active", health_status="healthy"),
            },
            service_mapping={"marketplace-service": "marketplace"},
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [{"name": "prod", "is_default": True}],
                    "default_environment": "prod",
                }
            }
        }

        result = build_context_string(execution_context, state)

        assert "Configured integrations: github (active, healthy)" in result
        assert "Not configured:" in result
        assert "Available services:" in result

    def test_excludes_integrations_when_flag_false(self):
        """Should not include integration status when include_integrations=False"""

        def _make_integration(status="active", health_status="healthy"):
            integration = MagicMock()
            integration.status = status
            integration.health_status = health_status
            return integration

        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={
                "github": _make_integration(status="active", health_status="healthy"),
            },
            service_mapping={"marketplace-service": "marketplace"},
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [{"name": "prod", "is_default": True}],
                    "default_environment": "prod",
                }
            }
        }

        result = build_context_string(
            execution_context, state, include_integrations=False
        )

        assert "Configured integrations" not in result
        assert "Not configured" not in result
        assert "Available services:" in result

    def test_integrations_appear_first_in_context_string(self):
        """Should place integration info at the beginning of context string"""

        def _make_integration(status="active", health_status="healthy"):
            integration = MagicMock()
            integration.status = status
            integration.health_status = health_status
            return integration

        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={
                "github": _make_integration(status="active", health_status="healthy"),
            },
            service_mapping={"marketplace-service": "marketplace"},
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [{"name": "prod", "is_default": True}],
                    "default_environment": "prod",
                }
            }
        }

        result = build_context_string(execution_context, state)

        # Integration info should appear before services
        integrations_pos = result.find("Configured integrations")
        services_pos = result.find("Available services")
        assert integrations_pos < services_pos


class TestGetDefaultEnvironment:
    """Tests for get_default_environment function"""

    def test_returns_default_environment(self):
        """Should return the default environment name"""
        state = {
            "context": {"environment_context": {"default_environment": "production"}}
        }
        result = get_default_environment(state)
        assert result == "production"

    def test_returns_none_when_not_set(self):
        """Should return None when default environment not set"""
        state = {"context": {"environment_context": {}}}
        result = get_default_environment(state)
        assert result is None

    def test_returns_none_when_context_missing(self):
        """Should return None when environment context missing"""
        state = {}
        result = get_default_environment(state)
        assert result is None


class TestGetEnvironmentList:
    """Tests for get_environment_list function"""

    def test_returns_environment_names(self):
        """Should return list of environment names"""
        state = {
            "context": {
                "environment_context": {
                    "environments": [
                        {"name": "dev", "is_default": False},
                        {"name": "prod", "is_default": True},
                    ]
                }
            }
        }
        result = get_environment_list(state)
        assert result == ["dev", "prod"]

    def test_returns_empty_list_when_no_environments(self):
        """Should return empty list when no environments"""
        state = {"context": {"environment_context": {"environments": []}}}
        result = get_environment_list(state)
        assert result == []

    def test_filters_invalid_entries(self):
        """Should filter out non-dict entries and entries without names"""
        state = {
            "context": {
                "environment_context": {
                    "environments": [
                        {"name": "prod", "is_default": True},
                        "invalid",  # Should be filtered
                        {"is_default": False},  # No name, should be filtered
                        {"name": "dev", "is_default": False},
                    ]
                }
            }
        }
        result = get_environment_list(state)
        assert result == ["prod", "dev"]


class TestGetDeployedCommits:
    """Tests for get_deployed_commits function"""

    def test_returns_deployed_commits_for_default_env(self):
        """Should return deployed commits for default environment"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123", "auth": "def456"},
                        "dev": {"marketplace": "xyz789"},
                    },
                }
            }
        }
        result = get_deployed_commits(state)
        assert result == {"marketplace": "abc123", "auth": "def456"}

    def test_returns_deployed_commits_for_specific_env(self):
        """Should return deployed commits for specified environment"""
        state = {
            "context": {
                "environment_context": {
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"},
                        "dev": {"marketplace": "xyz789"},
                    },
                }
            }
        }
        result = get_deployed_commits(state, environment_name="dev")
        assert result == {"marketplace": "xyz789"}

    def test_returns_empty_dict_when_env_not_found(self):
        """Should return empty dict when environment doesn't exist"""
        state = {
            "context": {
                "environment_context": {
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"}
                    }
                }
            }
        }
        result = get_deployed_commits(state, environment_name="staging")
        assert result == {}

    def test_returns_empty_dict_when_no_default(self):
        """Should return empty dict when no default environment set"""
        state = {
            "context": {"environment_context": {"deployed_commits_by_environment": {}}}
        }
        result = get_deployed_commits(state)
        assert result == {}


class TestGetContextSummary:
    """Tests for get_context_summary function"""

    def test_returns_complete_summary(self):
        """Should return complete context summary"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={
                "marketplace-service": "marketplace",
                "auth-service": "auth",
            },
        )
        state = {
            "context": {
                "environment_context": {
                    "environments": [
                        {"name": "dev", "is_default": False},
                        {"name": "prod", "is_default": True},
                    ],
                    "default_environment": "prod",
                    "deployed_commits_by_environment": {
                        "prod": {"marketplace": "abc123"}
                    },
                }
            }
        }

        result = get_context_summary(execution_context, state)

        assert result["services"] == ["marketplace-service", "auth-service"]
        assert result["service_count"] == 2
        assert result["service_mapping"] == {
            "marketplace-service": "marketplace",
            "auth-service": "auth",
        }
        assert result["environments"] == ["dev", "prod"]
        assert result["default_environment"] == "prod"
        assert result["env_count"] == 2
        assert result["deployed_commits"] == {"marketplace": "abc123"}

    def test_returns_summary_with_empty_data(self):
        """Should handle empty context gracefully"""
        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={},
            service_mapping={},
        )
        state = {}

        result = get_context_summary(execution_context, state)

        assert result["services"] == []
        assert result["service_count"] == 0
        assert result["service_mapping"] == {}
        assert result["environments"] == []
        assert result["default_environment"] is None
        assert result["env_count"] == 0
        assert result["deployed_commits"] == {}
        assert result["thread_history"] is None
        assert result["configured_integrations"] == []
        # Should include all known integration types as not configured
        assert "github" in result["not_configured_integrations"]
        assert "aws" in result["not_configured_integrations"]

    def test_returns_summary_with_configured_integrations(self):
        """Should include configured and not configured integrations in summary"""

        def _make_integration(status="active", health_status="healthy"):
            integration = MagicMock()
            integration.status = status
            integration.health_status = health_status
            return integration

        execution_context = ExecutionContext(
            workspace_id="test-workspace",
            capabilities=set(),
            integrations={
                "github": _make_integration(),
                "aws": _make_integration(),
            },
            service_mapping={},
        )
        state = {}

        result = get_context_summary(execution_context, state)

        assert "github" in result["configured_integrations"]
        assert "aws" in result["configured_integrations"]
        assert "github" not in result["not_configured_integrations"]
        assert "aws" not in result["not_configured_integrations"]
        # Other known integrations should be not configured
        assert "datadog" in result["not_configured_integrations"]
        assert "grafana" in result["not_configured_integrations"]
        assert "newrelic" in result["not_configured_integrations"]


class TestGetThreadHistory:
    """Tests for get_thread_history function"""

    def test_returns_thread_history(self):
        """Should return thread history string"""
        state = {
            "context": {
                "thread_history": "User: what envs do I have?\nBot: You have prod and dev."
            }
        }
        result = get_thread_history(state)
        assert result == "User: what envs do I have?\nBot: You have prod and dev."

    def test_returns_none_when_not_set(self):
        """Should return None when thread history not set"""
        state = {"context": {}}
        result = get_thread_history(state)
        assert result is None

    def test_returns_none_when_context_missing(self):
        """Should return None when context missing"""
        state = {}
        result = get_thread_history(state)
        assert result is None


class TestFormatThreadHistoryForPrompt:
    """Tests for format_thread_history_for_prompt function"""

    def test_formats_thread_history(self):
        """Should format thread history with prefix"""
        state = {
            "context": {"thread_history": "User: hi\nBot: Hello! How can I help you?"}
        }
        result = format_thread_history_for_prompt(state)
        assert (
            result
            == "Previous conversation:\nUser: hi\nBot: Hello! How can I help you?"
        )

    def test_returns_empty_when_no_history(self):
        """Should return empty string when no history"""
        state = {"context": {}}
        result = format_thread_history_for_prompt(state)
        assert result == ""

    def test_truncates_long_history(self):
        """Should truncate history that exceeds max_length"""
        long_history = "x" * 3000
        state = {"context": {"thread_history": long_history}}
        result = format_thread_history_for_prompt(state, max_length=100)

        # Should truncate and add ellipsis
        assert result.startswith("Previous conversation:\n...")
        assert len(result) <= 150  # "Previous conversation:\n" + "..." + 100 chars

    def test_respects_custom_max_length(self):
        """Should respect custom max_length parameter"""
        history = "User: question 1\nBot: answer 1\n" * 10  # ~300 chars
        state = {"context": {"thread_history": history}}

        result_50 = format_thread_history_for_prompt(state, max_length=50)
        result_200 = format_thread_history_for_prompt(state, max_length=200)

        # Shorter max_length should result in more truncation
        assert "..." in result_50
        assert len(result_50) < len(result_200)
