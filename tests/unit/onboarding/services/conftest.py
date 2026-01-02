"""
Conftest for onboarding services tests.

Provides properly scoped mocks for AuthService dependencies to avoid
polluting sys.modules globally and affecting other tests.
"""

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def mock_auth_service_dependencies():
    """
    Mock dependencies required by AuthService at import time.

    This fixture properly saves and restores sys.modules to avoid
    polluting other tests. Scoped to module level so the AuthService
    import happens once per test module.
    """
    # Save original modules
    original_modules = {}
    modules_to_mock = [
        "app.email",
        "app.email.service",
    ]

    for mod in modules_to_mock:
        if mod in sys.modules:
            original_modules[mod] = sys.modules[mod]

    # Create mocks
    mock_email_module = MagicMock()
    mock_email_module.email_service = MagicMock()

    # Install mocks
    sys.modules["app.email"] = mock_email_module
    sys.modules["app.email.service"] = mock_email_module

    yield {
        "email_service": mock_email_module.email_service,
    }

    # Restore original modules
    for mod in modules_to_mock:
        if mod in original_modules:
            sys.modules[mod] = original_modules[mod]
        elif mod in sys.modules:
            del sys.modules[mod]
